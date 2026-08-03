# -*- coding: utf-8 -*-
#
# Copyright (C) 2024 University of Chicago.
#
# chicago-invenio is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""DataCite PID provider subclass that supports restricted records."""

from datacite.errors import DataCiteError
from flask import current_app
from invenio_rdm_records.services.pids.providers.base import PIDProvider
from invenio_rdm_records.services.pids.providers.datacite import DataCitePIDProvider
from invenio_rdm_records.utils import ChainObject


class RestrictedDataCitePIDProvider(DataCitePIDProvider):
    """DataCite provider that mints and registers DOIs for restricted records.

    The upstream provider refuses to register DOIs for restricted records and
    deletes them during validation.  This subclass instead registers them in
    DataCite's "Registered" (non-findable) state so the DOI resolves but does
    not appear in DataCite search results.  When the record is later made open
    access the next update() call will promote it to "Findable" automatically
    (the upstream update() already handles this correctly).
    """

    def register(self, pid, record, **kwargs):
        """Register a DOI via the DataCite API.

        Restricted records are registered in DataCite's hidden ("Registered")
        state rather than being skipped.  The DOI resolves but is not findable
        in DataCite search until the record is made open access.
        """
        is_restricted = (
            record._child["access"]["record"] == "restricted"
            if isinstance(record, ChainObject)
            else record["access"]["record"] == "restricted"
        )

        if not is_restricted:
            return super().register(pid, record, **kwargs)

        # Mark the PID as registered in the local database (base class logic).
        local_success = PIDProvider.register(self, pid)
        if not local_success:
            return False

        try:
            doc = self.serializer.dump_obj(record)
            url = kwargs["url"]
            # Register the DOI at DataCite as findable, then immediately hide
            # it so it resolves but is not discoverable in DataCite search.
            self.client.api.public_doi(metadata=doc, url=url, doi=pid.pid_value)
            self.client.api.hide_doi(doi=pid.pid_value)
            return True
        except DataCiteError as e:
            current_app.logger.warning(
                f"DataCite provider error when registering restricted DOI for {pid.pid_value}"
            )
            self._log_errors(e)
            return False

    def validate_restriction_level(self, record, identifier=None, **kwargs):
        """Allow restricted records to retain their DOIs.

        The upstream implementation deletes NEW DOIs for restricted records.
        We override this to a no-op so that restricted records can hold a DOI
        in the local PID store and eventually have it registered at DataCite.
        """
        pass
