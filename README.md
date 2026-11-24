# Chicago Invenio

Welcome to your InvenioRDM instance.

## Getting started

### Development Setup

For development work, run the following commands to set up the environment:

```console
# Install dependencies and pre-commit hooks
make install

# Run code quality checks
make linter
```

### Running the Application

Run the following commands in order to start your new InvenioRDM instance:

```console
invenio-cli containers start --lock --build --setup
```

The above command first builds the application docker image and afterwards
starts the application and related services (database, Opensearch, Redis
and RabbitMQ). The build and boot process will take some time to complete,
especially the first time as docker images have to be downloaded during the
process.

Once running, visit https://127.0.0.1 in your browser.

**Note**: The server is using a self-signed SSL certificate, so your browser
will issue a warning that you will have to by-pass.

### Communities, collections and demo data

Publishing requires a community (`RDM_COMMUNITY_REQUIRED_TO_PUBLISH`), so the
Chicago communities and their collections must be loaded before records can be
published. They are defined in `site/chicago_invenio/scripts/com_col_data.csv`:
each `Community` value becomes a community, and each `Collection` value becomes
a collection in it, matching records on division, department, center/institute
and resource type.

The `chicago` CLI commands are registered through an entry point. After changing
`site/setup.cfg`, reinstall the site package with `pipenv run pip install -e ./site`.

**Demo data**: `invenio rdm-records demo` (run by `invenio-cli ... --setup`
unless `--no-demo-data` is given) is replaced with a Chicago version that:

- creates the communities and collections from the CSV, owned by
  `community@demo.org` (role `community-curator`)
- creates the record curator `curator@demo.org` (role `record-curator`)
- publishes records by `user@demo.org` into matching communities
- leaves drafts at each curation stage: awaiting curation, under review,
  and curation accepted (awaiting community review)

As with the stock demo, the records are created by Celery tasks, so they
appear once a worker (e.g. `invenio-cli run`) has processed them.

Demo users have the password `123456`. To change the numbers, run:

```console
invenio rdm-records demo records --records 100 --in-review 10
```

**Production**: load the communities and collections only, owned by an existing
user with the `community-curator` or `admin` role:

```console
invenio roles create community-curator
invenio roles create record-curator
invenio roles add <email> community-curator
invenio chicago communities --user <email>
```

Re-running it is safe. Existing communities are kept, and their collections
are rebuilt from the CSV.

## Overview

Following is an overview of the generated files and folders:

| Name | Description |
|---|---|
| ``Dockerfile`` | Dockerfile used to build your application image. |
| ``Pipfile`` | Python requirements installed via [pipenv](https://pipenv.pypa.io) |
| ``Pipfile.lock`` | Locked requirements (generated on first install). |
| ``app_data`` | Application data such as vocabularies. |
| ``assets`` | Web assets (CSS, JavaScript, LESS, JSX templates) used in the Webpack build. |
| ``docker`` | Example configuration for NGINX and uWSGI. |
| ``docker-compose.full.yml`` | Example of a full infrastructure stack. |
| ``docker-compose.yml`` | Backend services needed for local development. |
| ``docker-services.yml`` | Common services for the Docker Compose files. |
| ``invenio.cfg`` | The Invenio application configuration. |
| ``logs`` | Log files. |
| ``static`` | Static files that need to be served as-is (e.g. images). |
| ``templates`` | Folder for your Jinja templates. |
| ``.invenio`` | Common file used by Invenio-CLI to be version controlled. |
| ``.invenio.private`` | Private file used by Invenio-CLI *not* to be version controlled. |

## Documentation

To learn how to configure, customize, deploy and much more, visit
the [InvenioRDM Documentation](https://inveniordm.docs.cern.ch/).
