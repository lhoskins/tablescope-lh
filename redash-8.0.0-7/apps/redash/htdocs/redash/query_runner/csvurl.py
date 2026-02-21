from __future__ import absolute_import

from io import StringIO
import csv

import requests

from redash.query_runner import TYPE_STRING, BaseQueryRunner, register
from redash.utils import json_dumps


class CsvUrl(BaseQueryRunner):
    should_annotate_query = False

    @classmethod
    def name(cls):
        return "CSV (from URL)"

    @classmethod
    def configuration_schema(cls):
        return {
            "type": "object",
            "properties": {
                "username": {"title": "Username (Basic Auth)", "type": "string"},
                "password": {"title": "Password (Basic Auth)", "type": "string"},
            },
            "secret": ["password"],
        }

    def test_connection(self):
        pass

    def run_query(self, query, user):
        try:
            error = None
            url = query.strip()

            if "username" in self.configuration and self.configuration["username"]:
                auth = (self.configuration["username"], self.configuration["password"])
            else:
                auth = None

            response = requests.get(url, auth=auth)
            response.raise_for_status()
            raw_data = StringIO(response.text)
            reader = csv.DictReader(raw_data)

            columns = []
            rows = []

            for row in reader:
                if not columns:
                    columns = [
                        {"name": k, "friendly_name": k, "type": TYPE_STRING}
                        for k in row.keys()
                    ]

                rows.append({k: v for k, v in row.items()})

            json_data = json_dumps({"columns": columns, "rows": rows})

            return json_data, error
        except requests.RequestException as e:
            return None, str(e)
        except KeyboardInterrupt:
            error = "Query cancelled by user."
            json_data = None

        return json_data, error


register(CsvUrl)