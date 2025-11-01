import os
import sys
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError, ConnectionError
from dotenv import load_dotenv


load_dotenv()
# Configure client with retries and timeout, explicitly in us-east-1
def get_org_client():
  
    config = Config(
        region_name='us-east-1',          # Organizations ONLY works here
        retries={'max_attempts': 10, 'mode': 'standard'},
        read_timeout=30,
        connect_timeout=30
    )

    # You can force a profile via AWS_PROFILE, but we avoid it here
    return boto3.client('organizations', config=config)



def create_aws_organization(client):
    try:
        print("Creating organization with FeatureSet=ALL ...")
        resp = client.create_organization(FeatureSet='ALL')
        org = resp['Organization']
        print(f"Success: Organization ID {org['Id']}")
        return org

    except client.exceptions.AlreadyInOrganizationException:
        print("Already in an organization - fetching details...")
        try:
            org = client.describe_organization()['Organization']
            print(f"Existing org: {org['Id']}")
            return org
        except Exception as e:
            print(f"Failed to describe org: {e}")
            return None

    except ClientError as e:
        code = e.response['Error']['Code']
        msg  = e.response['Error']['Message']
        if code == 'AccessDeniedException':
            print("Access denied. Are you using the ROOT user credentials?")
        print(f"ClientError ({code}): {msg}")
        return None

    except (BotoCoreError, ConnectionError) as e:
        print(f"Network/BotoCore issue: {e}")
        return None

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return None
    
    
    
def main():
    # Show who we are running as (helpful for debugging)
    sts = boto3.client('sts')
    identity = sts.get_caller_identity()
    print(f"Running as: {identity['Arn']}")

    client = get_org_client()
    org = create_aws_organization(client)

    if org:
        print(f"Organization ARN: {org['Arn']}")
    else:
        print("Failed to create/retrieve organization.")
        sys.exit(1)

if __name__ == '__main__':
    main()   