#!/usr/bin/env python3
"""
setup.py for hermes-plugin-databricks.

Usage:
    python setup.py install       # install plugin into Hermes
    python setup.py uninstall     # remove plugin from Hermes
    python setup.py status        # show installation status
    python setup.py credentials   # manage credentials
    python setup.py log           # manage log level
    python setup.py audit         # check compliance
    python setup.py test          # run smoke tests
"""
from pathlib import Path
from hermes_plugin_core.setup_cli import SetupCLI, PluginConfig

config = PluginConfig(
    plugin_key="databricks",
    service="hermes-databricks",
    repo_dir=Path(__file__).parent.resolve(),
    keys=["host", "client_id", "client_secret", "warehouse_id"],
    cred_prompts={
        "host":           ("Workspace URL (e.g. https://dbc-e0b9d669-efb7.cloud.databricks.com)", "", False),
        "client_id":      ("Service Principal Client ID", "", False),
        "client_secret":  ("Client Secret", "", True),
        "warehouse_id":   ("SQL Warehouse ID (e.g. ed4e7a4296f9661b)", "", False),
    },
    requirements=[],
    has_skill_stub=True,
    skill_stub_category="data-science",
)

if __name__ == "__main__":
    SetupCLI(config).run()
