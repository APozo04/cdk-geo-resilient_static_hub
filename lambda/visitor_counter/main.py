import boto3
import hashlib
import time
import json
import os
from typing import Any, Dict
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# --- Environment Configuration ---
TABLE_NAME = os.environ.get('TABLE_NAME')
EXPECTED_TOKEN = os.environ.get('AUTH_TOKEN')

# Initialize DynamoDB Resource outside the handler for connection re-use
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(TABLE_NAME)

# --- IN-MEMORY CACHE CONFIGURATION ---
# These variables persist across invocations while the Lambda container is "warm"
CACHE_TTL = 10  # Time in seconds the cache is considered valid
_CACHE_STATS = None
_CACHE_EXPIRY = 0

def get_cached_stats(table_resource):
    """
    Retrieves stats from memory if valid, otherwise queries DynamoDB.
    This protects the database from read spikes during high traffic.
    """
    global _CACHE_STATS, _CACHE_EXPIRY
    now = time.time()

    # 1. Check if Cache is valid
    if _CACHE_STATS is not None and now < _CACHE_EXPIRY:
        print("⚡ Cache Hit: Serving stats from memory (No DB Read Cost)")
        return _CACHE_STATS

    # 2. Cache Miss or Expired: Fetch from DynamoDB
    print("🐢 Cache Miss: Querying DynamoDB GSI")
    try:
        response = table_resource.query(
            IndexName='MetricsIndex',
            KeyConditionExpression=Key('Type').eq('METRIC')
        )
        items = response.get('Items', [])
    except ClientError as e:
        print(f"Error fetching stats: {e}")
        items = []

    # 3. Process and Format Data
    stats = { "total_visits": 0, "countries": {}, "devices": {} }

    for item in items:
        pk = str(item['PK'])
        # DynamoDB returns numbers as Decimal, cast to int for JSON serialization
        count = int(item['count']) 
        
        if pk == 'TOTAL_VISITS':
            stats['total_visits'] = count
        elif pk.startswith('COUNTRY#'):
            stats['countries'][pk.split('#')[1]] = count
        elif pk.startswith('DEVICE#'):
            stats['devices'][pk.split('#')[1]] = count

    # 4. Update the Cache
    _CACHE_STATS = stats
    _CACHE_EXPIRY = now + CACHE_TTL
    
    return stats

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main entry point for the Visitor Counter API.
    1. Validates the X-Origin-Verify header.
    2. Identifies unique visitors via IP + User-Agent hashing.
    3. Prevents duplicate counts within a 30-minute window (Locking).
    4. Updates atomic counters for Total, Country, and Device type.
    5. Returns the latest statistics (Cached or Live).
    """
    
    # 1. Security: Origin Verification
    headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
    incoming_token = headers.get('x-origin-verify')

    if incoming_token != EXPECTED_TOKEN:
        print(f"Unauthorized access attempt. Received token: {incoming_token}")
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"message": "Forbidden: Invalid Origin Token"})
        }

    # 2. Metadata Extraction (CloudFront Viewer Headers)
    ip_address = headers.get('cloudfront-viewer-address', 'unknown')
    user_agent = headers.get('user-agent', 'unknown')
    country_code = headers.get('cloudfront-viewer-country', 'XX')
    
    # Determine Device Type
    if headers.get('cloudfront-is-mobile-viewer') == 'true':
        device_type = 'Mobile'
    elif headers.get('cloudfront-is-tablet-viewer') == 'true':
        device_type = 'Tablet'
    else:
        device_type = 'Desktop'

    # 3. Visitor Deduplication (30-minute Cooldown)
    visitor_id = hashlib.sha256(f"{ip_address}{user_agent}".encode()).hexdigest()
    cooldown_seconds = 1800 
    expires_at = int(time.time()) + cooldown_seconds
    status = "Ignored"

    try:
        # Atomic locking: Only succeeds if the PK doesn't exist (or has expired)
        table.put_item(
            Item={
                'PK': f"LOCK#{visitor_id}", 
                'ExpiresAt': expires_at
            },
            ConditionExpression='attribute_not_exists(PK)'
        )
        
        # 4. Atomic Metric Increments
        # These operations are thread-safe and handled by DynamoDB directly
        try:
            update_exp = "SET #t = :t ADD #c :v"
            attr_names = {"#c": "count", "#t": "Type"}
            attr_vals = {":v": 1, ":t": "METRIC"}

            # Increment Total, Country, and Device metrics
            table.update_item(Key={'PK': 'TOTAL_VISITS'}, UpdateExpression=update_exp, ExpressionAttributeNames=attr_names, ExpressionAttributeValues=attr_vals)
            table.update_item(Key={'PK': f"COUNTRY#{country_code}"}, UpdateExpression=update_exp, ExpressionAttributeNames=attr_names, ExpressionAttributeValues=attr_vals)
            table.update_item(Key={'PK': f"DEVICE#{device_type}"}, UpdateExpression=update_exp, ExpressionAttributeNames=attr_names, ExpressionAttributeValues=attr_vals)
            
            status = "New visit counted"
        except ClientError as e:
            print(f"Metrics Update Error: {e.response['Error']['Message']}")
            status = "Error updating metrics"

    except ClientError as e:
        # ConditionalCheckFailedException means the visitor is still in cooldown
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            status = "Reload ignored (Cooldown active)"
        else:
            print(f"Locking Error: {e.response['Error']['Message']}")

    # 5. Data Retrieval (OPTIMIZED WITH CACHE)
    # Instead of querying DynamoDB every time, we check the memory first.
    stats = get_cached_stats(table)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "status": status,
            "visitor": {
                "country": country_code, 
                "device": device_type
            },
            "statistics": stats
        })
    }