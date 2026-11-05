import logging
import os

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Connect timeout and read inactivity timeout, in seconds (not a total deadline).
HTTP_TIMEOUT = (5, 30)


# Function to get an access token from Microsoft Graph
def get_microsoft_token():
    tenant_id = os.getenv("TENANT_ID")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    if not tenant_id or not client_id or not client_secret:
        raise ValueError("TENANT_ID, CLIENT_ID, and CLIENT_SECRET must be set")

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    body = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    response = requests.post(url, data=body, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code != 200:
        logger.error("Error getting Microsoft token: %s", response.text)
        return None
    logger.info("Successfully obtained Microsoft token.")
    return response.json().get("access_token")


# Function to fetch Azure AD groups
def get_azure_groups(token):
    url = "https://graph.microsoft.com/v1.0/groups"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code != 200:
        logger.error("Error getting Azure AD groups: %s", response.text)
        return []
    logger.info("Successfully fetched Azure AD groups.")
    return response.json().get("value", [])


# Function to fetch members of a specific Azure AD group
def get_group_members(group_id, token):
    url = f"https://graph.microsoft.com/v1.0/groups/{group_id}/members"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code != 200:
        logger.error(
            "Error getting group members for group %s: %s", group_id, response.text
        )
        return []
    logger.info("Successfully fetched members for group %s.", group_id)
    return response.json().get("value", [])


# Function to get Grafana users by email to map userId for adding to teams
def get_grafana_users():
    grafana_url = os.getenv("GRAFANA_URL")
    grafana_api_key = os.getenv("GRAFANA_API_KEY")
    url = f"{grafana_url}/api/org/users"
    headers = {"Authorization": f"Bearer {grafana_api_key}"}
    response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code != 200:
        logger.error("Error fetching Grafana users: %s", response.text)
        return []
    return response.json()


# Function to fetch Grafana teams
def get_grafana_teams():
    grafana_url = os.getenv("GRAFANA_URL")
    grafana_api_key = os.getenv("GRAFANA_API_KEY")
    url = f"{grafana_url}/api/teams/search?perpage=1000&page=1"
    headers = {"Authorization": f"Bearer {grafana_api_key}"}
    response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code != 200:
        logger.error("Error fetching Grafana teams: %s", response.text)
        return []
    return response.json().get("teams", [])


# Function to update Grafana team members with userId
def update_grafana_team_members(team_id, members, grafana_users):
    grafana_url = os.getenv("GRAFANA_URL")
    grafana_api_key = os.getenv("GRAFANA_API_KEY")
    url = f"{grafana_url}/api/teams/{team_id}/members"
    headers = {
        "Authorization": f"Bearer {grafana_api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Map the emails from Azure AD members to Grafana userIds
    current_members = []
    for member in members:
        email = member.get("email") or member.get("userPrincipalName")
        if email:
            # Find userId in Grafana for the corresponding email
            grafana_user = next(
                (user for user in grafana_users if user["email"] == email), None
            )
            if grafana_user:
                current_members.append(grafana_user["userId"])

    # Fetch current team members
    response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code != 200:
        logger.error(
            "Error fetching current team members for team %s: %s",
            team_id,
            response.text,
        )
        return

    current_team_members = response.json()
    logger.debug(
        "Grafana team members before sync for team %s: %s",
        team_id,
        current_team_members,
    )

    # Log the current members of the team
    logger.debug(
        "Comparing the following members from Azure AD with Grafana team members:"
    )
    logger.debug("Azure AD group members: %s", current_members)

    # Add new members (only those who are not already in the team)
    for user_id in current_members:
        if user_id not in [m["userId"] for m in current_team_members]:
            # Add user to Grafana team only if they are not already in the team
            data = {"userId": user_id}
            response = requests.post(
                url, headers=headers, json=data, timeout=HTTP_TIMEOUT
            )
            if response.status_code == 200:
                logger.info("Added userId %s to Grafana team.", user_id)
            else:
                logger.error(
                    "Error adding userId %s to Grafana team: %s", user_id, response.text
                )

    # Fetch and log the team members after syncing
    response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code == 200:
        current_team_members_after_sync = response.json()
        logger.debug(
            "Grafana team members after sync for team %s: %s",
            team_id,
            current_team_members_after_sync,
        )
    else:
        logger.error(
            "Error fetching current team members after sync for team %s: %s",
            team_id,
            response.text,
        )


# Main sync function
def sync_teams():
    grafana_url = os.getenv("GRAFANA_URL")
    grafana_api_key = os.getenv("GRAFANA_API_KEY")
    if not grafana_url or not grafana_api_key:
        raise ValueError("GRAFANA_URL and GRAFANA_API_KEY must be set")

    sync_groups = {
        name.strip() for name in os.getenv("SYNC_GROUPS", "").split(",") if name.strip()
    }
    if not sync_groups:
        raise ValueError("SYNC_GROUPS must contain at least one group name")

    token = get_microsoft_token()
    if not token:
        return

    azure_groups = get_azure_groups(token)
    if not azure_groups:
        logger.warning("No Azure AD groups found.")
        return

    grafana_teams = get_grafana_teams()
    if not grafana_teams:
        logger.warning("No teams found in Grafana.")
        return

    # Loop through all the Azure AD groups
    for group in azure_groups:
        group_name = group.get("displayName", "None")

        # Only log and sync specific groups in the sync_groups list
        if group_name in sync_groups:
            logger.debug("Checking Azure AD group: %s", group_name)
            for team in grafana_teams:
                # Log the team name and group name to check if they match
                logger.debug(
                    "Checking if Azure AD group '%s' matches Grafana team '%s'",
                    group_name,
                    team["name"],
                )
                if team["name"] == group_name:
                    logger.info(
                        "Syncing group %s with Grafana team %s.",
                        group_name,
                        team["name"],
                    )
                    members = get_group_members(group["id"], token)
                    grafana_users = get_grafana_users()
                    update_grafana_team_members(team["id"], members, grafana_users)
                else:
                    logger.debug(
                        "Skipping sync: Group '%s' does not match Grafana team '%s'.",
                        group_name,
                        team["name"],
                    )
        else:
            # Skip logging for groups not in the sync_groups list
            continue


def main() -> None:
    """Run the Entra ID to Grafana team synchronization."""
    load_dotenv()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sync_teams()


if __name__ == "__main__":
    main()
