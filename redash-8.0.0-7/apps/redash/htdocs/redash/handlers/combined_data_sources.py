import logging
from flask import jsonify
from redash.handlers.base import BaseResource
from redash.models import DataSource
from redash.authentication import current_org
from redash.services.vdb_context import VDBContextService
from collections import OrderedDict
import json

# Create a logger instance
logger = logging.getLogger(__name__)

class CombinedDataSourcesResource(BaseResource):
    def get(self):
        try:
            # Fetch internal data sources
            internal_data_sources = DataSource.query.all()
            logger.info("Fetched internal data sources count: %d", len(internal_data_sources))

            internal_sources = [
                OrderedDict([
                    ("name", ds.name),
                    ("pause_reason", getattr(ds, "pause_reason", None)),
                    ("syntax", getattr(ds, "syntax", "sql")),
                    ("paused", getattr(ds, "paused", 0)),
                    ("view_only", getattr(ds, "view_only", False)),
                    ("type", getattr(ds, "type", "internal")),
                    ("id", ds.id),
                ]) for ds in internal_data_sources
            ]
            logger.debug("Internal data sources: %s", internal_sources)

            # Get VDB name for current organization
            try:
                org_id = current_org.id
                vdb_config = VDBContextService.get_vdb_for_organization(org_id)
                if vdb_config:
                    data_source_name = vdb_config.vdb_id
                    logger.info("Using VDB '{}' for org {}".format(data_source_name, org_id))
                else:
                    # Fallback to default VDB if no org-specific VDB configured
                    data_source_name = "myvdbtest"
                    logger.warning("No VDB configured for org {}, using default: {}".format(org_id, data_source_name))
            except Exception as e:
                logger.error("Failed to get VDB for organization: {}".format(str(e)))
                data_source_name = "myvdbtest"
                logger.warning("Using default VDB: {}".format(data_source_name))
            
            # Fetch external data sources from the organization's virtual database
            data_source = DataSource.get_by_name(data_source_name)
            if not data_source:
                logger.error("Data source '%s' not found", data_source_name)
                return {"error": "Data source not found"}, 404

            query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'MyCompany' 
            AND table_name NOT LIKE '%_XLS%' 
            AND table_name NOT LIKE '%_CSV%' 
            AND table_name NOT LIKE '%_TXT%'
            """
            query_result, error = data_source.query_runner.run_query(query, None)

            if error:
                logger.error("Error running query: %s", error)
                return {"error": error}, 500

            query_result_json = json.loads(query_result)
            logger.info("External data sources fetched successfully")

            external_sources = [
                OrderedDict([
                    ("name", row["table_name"]),
                    ("pause_reason", None),
                    ("syntax", "sql"),
                    ("paused", 0),
                    ("view_only", False),
                    ("type", "external"),
                    ("id", 1000 + index)
                ]) for index, row in enumerate(query_result_json["rows"])
            ]
            logger.debug("External data sources: %s", external_sources)

            # Combine and sort data sources
            combined_sources = internal_sources + external_sources
            logger.info("Combined sources before sorting: %s", combined_sources)

            combined_sources.sort(key=lambda x: x["name"])
            logger.info("Combined sources after sorting: %s", combined_sources)

            return jsonify(combined_sources)

        except Exception as e:
            logger.exception("An error occurred while fetching combined data sources")
            return {"error": str(e)}, 500
