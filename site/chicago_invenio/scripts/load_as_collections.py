import csv
import json
import sys
import re, unicodedata

from invenio_collections.api import CollectionTree, Collection
from invenio_collections.proxies import current_collections
from invenio_access.permissions import system_identity

from invenio_db import db

from invenio_communities.proxies import current_communities
svc = current_communities.service

import os

def rel2abs(src, *paths):
    src = os.path.realpath(src)
    if os.path.isfile(src):
        src = os.path.dirname(src)
    return os.path.abspath(os.path.join(src, *paths))

CSV = rel2abs(__file__, 'com_col_data.csv')
COM = "61943e3d-9bf3-40e3-822c-2f3a14557515"

# from invenio_rdm_records.proxies import current_record_communities_service
# from invenio_communities.proxies import current_communities

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

def load_collections(structure, community_id):
    ctree = CollectionTree.resolve(slug="collections", community_id=community_id)
    if ctree is None:
        ctree = CollectionTree.create(title="Collections", slug="collections", community_id=community_id)

    for c in ctree.collections:
        db.session.delete(c.model)
    db.session.commit()


    collections_service = current_collections.service

    for k, v in structure.items():
        parent = collections_service.create(
            system_identity,
            v.get("community_id", community_id),
            tree_slug=ctree.slug,
            slug=k,
            title=v.get("title", k),
            query=v.get("query"),
            order=v.get("order", 10),
        )

        for ck, cv in v.get("children", {}).items():
            collections_service.add(
                system_identity,
                collection=parent._collection,
                slug=ck,
                title=cv.get("title", ck),
                query=cv.get("query"),
                order=cv.get("order", 10),
            )

def to_collection_tree(structure, community_id):
    tree = {}
    po = 10
    for k, v in structure.items():
        slug = slugify(k)
        tree[slug] = {
            "community_id": community_id,
            "title": k,
            "query": parent_query_for(v),
            "order": po,
            "children": {}
        }
        po += 10

        co = 10
        ctx = tree[slug]["children"]
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

def slugify(text):
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    # remove punctuation (keep letters, numbers, whitespace and hyphens)
    text = re.sub(r'[^\w\s-]', '', text)
    # replace whitespace/underscores with hyphens and collapse consecutive hyphens
    text = re.sub(r'[\s_]+', '-', text.strip().lower())
    return text.strip('-')

FIELD_MAP = {
    "division": "custom_fields.division.keyword",
    "department": "custom_fields.department.keyword",
    "center": "custom_fields.center_or_institute.keyword",
    "resource_type": "resource_type.id.keyword",
}

def child_query_for(rules):
    ands = []
    for k, v in rules.items():
        field = FIELD_MAP[k]
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


def main(csv_path, community_id):
    nested = build_nested_dict(csv_path)
    # print(json.dumps(nested, ensure_ascii=False, indent=2))
    tree = to_collection_tree(nested, community_id)
    # print(json.dumps(tree, ensure_ascii=False, indent=2))
    load_collections(tree, community_id)

if __name__ == '__main__':
    # import argparse
    #
    # parser = argparse.ArgumentParser()
    # parser.add_argument("community", help="ID of the community to use as root")
    # parser.add_argument("input_csv", help="Path to input CSV file")
    # args = parser.parse_args()

    # main(args.input_csv, args.community)
    main(CSV, COM)
    # sys.exit()

