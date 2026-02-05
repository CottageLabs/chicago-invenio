import csv
import json
import os
import sys

from invenio_collections.api import CollectionTree, Collection
from invenio_collections.errors import CollectionTreeNotFound
from invenio_collections.proxies import current_collections
from flask import current_app
from invenio_app.factory import create_app
from invenio_db import db
from invenio_communities.proxies import current_communities
from invenio_rdm_records.fixtures.tasks import get_authenticated_identity
from marshmallow import ValidationError

from chicago_invenio.scripts.utils import slugify


def rel2abs(src, *paths):
    src = os.path.realpath(src)
    if os.path.isfile(src):
        src = os.path.dirname(src)
    return os.path.abspath(os.path.join(src, *paths))

CSV = rel2abs(__file__, 'com_col_data.csv')


def build_nested_dict(csv_path):
    nested = {}
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.reader(fh)
        # skip header
        try:
            next(reader)
        except StopIteration:
            return nested

        for row in reader:
            # Ensure row has at least 6 columns
            row = row + [''] * (6 - len(row))
            # indices: 0..5 correspond to columns 1..6
            division = row[0].strip()
            department = row[1].strip()
            center = row[2].strip()
            resource_type = row[3].strip()
            parent_key = row[4].strip()
            child_key = row[5].strip()

            # skip rows without a parent (5th column empty)
            if not parent_key:
                continue

            parent = nested.setdefault(parent_key, {})

            # may use empty string as valid child key when 6th col empty
            # which means that the rules apply to the parent itself
            if child_key not in parent:
                parent[child_key] = []

            # Helper to set value only if non-empty and not already set
            def set_if_present(target_dict, key_name, value):
                if value and key_name not in target_dict:
                    target_dict[key_name] = value

            child_settings = {}
            set_if_present(child_settings, 'division', division)
            set_if_present(child_settings, 'department', department)
            set_if_present(child_settings, 'center', center)
            set_if_present(child_settings, 'resource_type', resource_type)

            parent[child_key].append(child_settings)

    return nested

def load_structure(structure, identity):

    communities_service = current_communities.service
    collections_service = current_collections.service

    slug_id_map = {}

    for k, v in structure.items():
        # locate a community if one exists, and delete it
        # FIXME: finds, but does not delete the community, so the script cannot be re-run
        #
        # model = communities_service.config.record_cls.model_cls
        # c_record = db.session.query(model).filter_by(slug=k).one_or_none()
        # if c_record is not None:
        #     print("Deleting existing community:", k)
        #     db.session.delete(c_record)
        #     db.session.commit()

        # com = None
        # if c_record is not None:
        #     com = communities_service.service.result_item_cls(communities_service, system_identity, c_record)
        #
        # if com is not None:

        # create a new community
        community_id = None
        try:
            com = communities_service.create(
                data={
                    "slug": k,
                    "metadata": v.get("metadata", {"title": k}),
                    "access": v.get("access", {"visibility" : "public"}),
                    "children": {"allow": True}
                },
                identity=identity,
            )
            community_id = com.id
        except ValidationError:
            print("Community creation failed (already exists?):", k)
            # Example search for community by slug
            params = {
                'q': f'slug:"{k}"'
            }
            results = list(communities_service.search(identity, params).hits)

            if results and len(results) > 0:
                # print(type(results[0]))
                # print(results[0]['id'])
                community_id = results[0]['id']

            else:
                continue

        # create a collection tree in the community
        try:
            ctree = CollectionTree.resolve(slug=f"{k}-collections", community_id=community_id)
        except CollectionTreeNotFound:
            ctree = CollectionTree.create(title="Collections", slug=f"{k}-collections", community_id=community_id)

        # delete any existing collections
        for c in ctree.collections:
            db.session.delete(c.model)
        db.session.commit()

        # create collections in the tree for the community
        for ck, cv in v.get("collections", {}).items():
            try:
                collections_service.create(
                    identity,
                    community_id,
                    tree_slug=ctree.slug,
                    slug=ck,
                    title=cv.get("title", ck),
                    query=cv.get("query"),
                    order=cv.get("order", 10),
                )
            except Exception:
                pass

        # Map original community title (not slugified) to community ID  
        community_title = v.get("metadata", {}).get("title", k)
        if community_title not in slug_id_map:
            slug_id_map[community_title] = community_id

    return slug_id_map

def to_com_col_tree(structure):
    tree = {}
    for k, v in structure.items():
        slug = slugify(k)
        tree[slug] = {
            "metadata": {
                "title": k
            },
            "access": {"visibility": "public"},
            "collections": {}
        }

        co = 10
        ctx = tree[slug]["collections"]
        for k1, v1 in v.items():
            if k1 != "":
                slug1 = slugify(k + "-" + k1)
                ctx[slug1] = {
                    "title": k1,
                    "query": all_child_query_for(v1),
                    "order": co
                }
                co += 10

    return tree

FIELD_MAP = {
    "division": "custom_fields.chicago\\:division",
    "department": "custom_fields.chicago\\:department",
    "center": "custom_fields.chicago\\:center_or_institute",
    "resource_type": "metadata.resource_type.id",
}

# Map human-readable resource type names to InvenioRDM resource_type IDs
RESOURCE_TYPE_MAP = {
    "Dissertation": "publication-dissertation",
    "Thesis": "publication-thesis",
    "Article": "publication-article",
    "Book": "publication-book",
    "Report": "publication-report",
    "Dataset": "dataset",
    "Patent": "publication-patent",
}


def child_query_for(rules):
    ands = []
    for k, v in rules.items():
        field = FIELD_MAP[k]
        # Translate resource_type values to InvenioRDM IDs
        if k == "resource_type" and v in RESOURCE_TYPE_MAP:
            v = RESOURCE_TYPE_MAP[v]
        ands.append(f'{field}:"{v}"')

    return "(" + ") AND (".join(ands) + ")"


def all_child_query_for(rules):
    ors = []
    for set in rules:
        ors.append(child_query_for(set))

    return "(" + ") OR (".join(ors) + ")"


def parent_query_for(rules):
    default = rules.get("")
    ors = []
    if default is not None:
        for set in default:
            ors.append(child_query_for(set))
    else:
        for k, v in rules.items():
            for sub in v:
                ors.append(child_query_for(sub))

    return "(" + ") OR (".join(ors) + ")"


def main(email_or_identity, csv_path=CSV):
    if isinstance(email_or_identity, str):
        # Create application context
        app = create_app()
        with app.app_context():
            # Find the user
            user_datastore = current_app.extensions["security"].datastore
            owner = user_datastore.find_user(email=email_or_identity)

            if not owner:
                print(f"User with email {email_or_identity} not found.")
                sys.exit(1)

            identity = get_authenticated_identity(owner.id)
    else:
        identity = email_or_identity

    nested = build_nested_dict(csv_path)
    # print(json.dumps(nested, ensure_ascii=False, indent=2))
    tree = to_com_col_tree(nested)
    # print(json.dumps(tree, ensure_ascii=False, indent=2))
    slug_id_map = load_structure(tree, identity)

    print(slug_id_map)

    return slug_id_map

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    # parser.add_argument("community", help="ID of the community to use as root")
    # parser.add_argument("input_csv", help="Path to input CSV file")
    args = parser.parse_args()

    # main(args.input_csv, args.community)
    main(args.email)
    # sys.exit()

