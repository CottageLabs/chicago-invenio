# Dockerfile that builds a fully functional image of your app.
#
# This image installs all Python dependencies for your application. It's based
# on Almalinux (https://github.com/inveniosoftware/docker-invenio)
# and includes Pip, Pipenv, Node.js, NPM and some few standard libraries
# Invenio usually needs.
#
# Note: It is important to keep the commands in this file in sync with your
# bootstrap script located in ./scripts/bootstrap.

# --- build stage: compiles Python packages and frontend assets ---
FROM registry.cern.ch/inveniosoftware/almalinux:1 AS builder

# 2025-09-17
# This is a manual edit to install Python 3.12 as the base image comes with 3.9
RUN dnf -y install --nodocs python3.12 python3.12-devel python3.12-libs python3.12-pip gcc gcc-c++ make && \
    dnf clean all && rm -rf /var/cache/dnf

RUN alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    alternatives --set python3 /usr/bin/python3.12

RUN pip install --upgrade pip pipenv

COPY Pipfile Pipfile.lock ./
COPY site ./site
RUN PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

COPY static ./static
COPY assets ./assets

ENV PATH="/opt/invenio/src/.venv/bin:${PATH}"
RUN cp -r ./static/. ${INVENIO_INSTANCE_PATH}/static/ && \
    cp -r ./assets/. ${INVENIO_INSTANCE_PATH}/assets/ && \
    invenio collect --verbose && \
    invenio webpack buildall

# --- runtime stage: no build tools, no Node.js, no dev headers ---
FROM registry.cern.ch/inveniosoftware/almalinux:1

RUN dnf -y install --nodocs python3.12 python3.12-libs && \
    dnf clean all && rm -rf /var/cache/dnf

RUN alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    alternatives --set python3 /usr/bin/python3.12

COPY --from=builder /opt/invenio/src/.venv /opt/invenio/src/.venv
ENV PATH="/opt/invenio/src/.venv/bin:${PATH}"

COPY --from=builder ${INVENIO_INSTANCE_PATH}/static ${INVENIO_INSTANCE_PATH}/static

COPY ./docker/uwsgi/ ${INVENIO_INSTANCE_PATH}
COPY ./invenio.cfg ${INVENIO_INSTANCE_PATH}
COPY ./templates/ ${INVENIO_INSTANCE_PATH}/templates/
COPY ./app_data/ ${INVENIO_INSTANCE_PATH}/app_data/
COPY ./translations/ ${INVENIO_INSTANCE_PATH}/translations/
COPY ./site ./site

ENTRYPOINT [ "bash", "-c"]
