"""
Module for Terraform Enterprise/Cloud Migration Worker: Workspaces.
"""

import sys
import os
import json
import http.client

from .base_worker import TFCMigratorBaseWorker

class WorkspacesWorker(TFCMigratorBaseWorker):
    """
    A class to represent the worker that will migrate all workspaces from one
    TFC/E org to another TFC/E org.
    """

    _api_module_used = "workspaces"
    _required_entitlements = []

    def migrate_all(self, agent_pools_map):
        """
        Function to migrate all workspaces from one TFC/E org to another TFC/E org.
        """

        self._logger.info("Migrating workspaces...")

        source_workspaces = {}

        loadFromDumpFile = True
        if (loadFromDumpFile): # load the workspace info from a dump file
            self._logger.info("Grabbing workspaces from Dump File...")
            source_workspaces = json.load(open("NewWorkspacePayload.json"))
        else: # hit the API to grab the source workspaces
            self._logger.info("Grabbing workspaces from the hitting API...")
            workspacesToGrab = {"ws-1xKs7xLA2nP3ExYd"} #sandbox testing
            # Fetch workspaces from existing org
            source_workspaces = self._api_source.workspaces.list_all()
            # grab the desired workspaces
            source_workspaces = [x for x in source_workspaces if x['id'] in workspacesToGrab]

        target_workspaces = self._api_target.workspaces.list_all()
      
        # make sure to lock the workspace
        for workspace in source_workspaces:
            if (not workspace["attributes"]["locked"]):
                print("Locking " + str(workspace["attributes"]["name"]) + "...")
                self._api_source.workspaces.lock(workspace["id"], None)
            else:
                print(str(workspace["attributes"]["name"]) + " is already locked. Moving on.")

        target_workspaces_data = {}
        for target_workspace in target_workspaces:
            target_workspaces_data[target_workspace["attributes"]["name"]] = target_workspace["id"]

        workspaces_map = {}
        workspace_to_ssh_key_map = {}

        vcsMapping = json.load(open('vcsMapping.json'))

        for source_workspace in source_workspaces:
            source_workspace_name = source_workspace["attributes"]["name"]
            source_workspace_id = source_workspace["id"]

            if source_workspace_name in target_workspaces_data:
                workspaces_map[source_workspace_id] = target_workspaces_data[source_workspace_name]

                if "ssh-key" in source_workspace["relationships"]:
                    ssh_key = source_workspace["relationships"]["ssh-key"]["data"]["id"]
                    workspace_to_ssh_key_map[source_workspace["id"]] = ssh_key

                self._logger.info("Workspace: %s, exists. Skipped.", source_workspace_name)
                continue

            branch = "" if source_workspace["attributes"]["vcs-repo"] is None \
                else source_workspace["attributes"]["vcs-repo"]["branch"]

            ingress_submodules = False if source_workspace["attributes"]["vcs-repo"] is None \
                else source_workspace["attributes"]["vcs-repo"]["ingress-submodules"]

            default_branch = True if branch == "" else False

            new_workspace_payload = {
                "data": {
                    "attributes": {
                        "name": source_workspace_name,
                        "terraform_version": source_workspace["attributes"]["terraform-version"],
                        "working-directory": source_workspace["attributes"]["working-directory"],
                        "file-triggers-enabled": \
                            source_workspace["attributes"]["file-triggers-enabled"],
                        "allow-destroy-plan": source_workspace["attributes"]["allow-destroy-plan"],
                        "auto-apply": source_workspace["attributes"]["auto-apply"],
                        "execution-mode": source_workspace["attributes"]["execution-mode"],
                        "description": source_workspace["attributes"]["description"],
                        "source-name": source_workspace["attributes"]["source-name"],
                        "source-url": source_workspace["attributes"]["source-url"],
                        "queue-all-runs": source_workspace["attributes"]["queue-all-runs"],
                        "speculative-enabled": \
                            source_workspace["attributes"]["speculative-enabled"],
                        "trigger-prefixes": source_workspace["attributes"]["trigger-prefixes"],
                    },
                    "type": "workspaces"
                }
            }

            # Set agent pool ID unless target is TFE
            if source_workspace["attributes"]["execution-mode"] == "agent":
                if agent_pools_map and 'app.terraform.io' in self._api_target.get_url():
                    new_workspace_payload["data"]["attributes"]["agent-pool-id"] = \
                        agent_pools_map[\
                            source_workspace["relationships"]["agent-pool"]["data"]["id"]]
                else:
                    new_workspace_payload["data"]["attributes"]["execution-mode"] = "remote"

            if source_workspace["attributes"]["vcs-repo"] is not None:
                oauth_token_id = ""
                for vcs_connection in self._vcs_connection_map:
                    if vcs_connection["source"] == \
                        source_workspace["attributes"]["vcs-repo"]["oauth-token-id"]:
                        oauth_token_id = vcs_connection["target"]

                #grab the repo identifier from the json mapping using source_workspace_name
                repoId = vcsMapping[source_workspace_name]["target"]

                new_workspace_payload["data"]["attributes"]["vcs-repo"] = {
                    "identifier": repoId,
                    "oauth-token-id": oauth_token_id,
                    "branch": branch,
                    "default-branch": default_branch,
                    "ingress-submodules": ingress_submodules
                }

            # Build the new workspace
            new_workspace = self._api_target.workspaces.create(new_workspace_payload)
            self._logger.info("Workspace: %s, created.", source_workspace_name)

            new_workspace_id = new_workspace["data"]["id"]
            workspaces_map[source_workspace["id"]] = new_workspace_id

            if "ssh-key" in source_workspace["relationships"]:
                ssh_key = source_workspace["relationships"]["ssh-key"]["data"]["id"]
                workspace_to_ssh_key_map[source_workspace["id"]] = ssh_key

            # TEMPORARY - add DevOps team access for testing visibility
            addDevOpsAccess = True
            if (addDevOpsAccess):
                new_workspace_team_payload = {
                    "data": {
                        "attributes": {
                            "access": "write"
                        },
                        "relationships": {
                            "workspace": {
                                "data": {
                                    "type": "workspaces",
                                    "id": new_workspace_id
                                }
                            },
                            "team": {
                                "data": {
                                    "type": "teams",
                                    "id": "team-EDStmjgwHqJgAmck"
                                }
                            }
                        },
                        "type": "team-workspaces"
                    }
                }
                self._api_target.team_access.add_team_access(new_workspace_team_payload)
            
            # add tags to each workspace we migrate 
            tagPayload = {
                "data": [
                    {
                        "type": "tags",
                        "attributes": {
                            "name": "team:devops"
                        }
                    },
                    {
                        "type": "tags",
                        "attributes": {
                            "name": "MigratedFromTFE"
                        }
                    }
                ]
            }
            self.add_tags_to_workspace(new_workspace_id, tagPayload)

        self._logger.info("Workspaces migrated.")
        return workspaces_map, workspace_to_ssh_key_map


    def delete_all_from_target(self):
        """
        Function to delete all workspaces from the target TFC/E org.
        """

        self._logger.info("Deleting workspaces...")

        workspaces = self._api_target.workspaces.list_all()

        if workspaces:
            for workspace in workspaces:
                self._api_target.workspaces.destroy(workspace["id"])
                self._logger.info("Workspace: %s, deleted.", workspace["attributes"]["name"])

        self._logger.info("Workspaces deleted.")

    
    def add_tags_to_workspace(self, workspace_id, payload):
        print("Adding tags to workspace...")
        conn = http.client.HTTPSConnection("app.terraform.io")
        payload = json.dumps(payload)
        headers = {
            'Content-Type': 'application/vnd.api+json',
            'Authorization': 'Bearer ' + os.environ['TFE_TOKEN_TARGET']
        }
        conn.request("POST", "/api/v2/workspaces/" + workspace_id + "/relationships/tags", payload, headers)
        
        res = conn.getresponse()
        if (res.status == 204):
            print("Tags successfully added.")
        else:
            print("Failed to add tags. Reason: " + res.reason)