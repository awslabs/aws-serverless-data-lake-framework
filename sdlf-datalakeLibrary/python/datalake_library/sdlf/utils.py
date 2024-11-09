import datetime
import time
import uuid


def get_duration_sec(start_timestamp_str, end_timestamp_str):
    ts_format = "%Y-%m-%dT%H:%M:%S.%f%z"
    start_ts = datetime.datetime.strptime(start_timestamp_str, ts_format)
    end_ts = datetime.datetime.strptime(end_timestamp_str, ts_format)
    return (end_ts - start_ts).total_seconds()


# datetime.datetime.now(datetime.UTC)
def get_timestamp_iso(current_time=datetime.datetime.now(datetime.UTC)):
    return current_time.isoformat()


# Return local date ISO formatted
def get_local_date(local_time=datetime.datetime.now()):
    return local_time.strftime("%Y-%m-%d")


def is_not_empty(arg):
    return (arg is not None) and (len(arg) != 0)


def throw_if_none(arg, msg):
    if arg is None:
        raise ValueError(msg)


def throw_none_or_empty(arg, msg):
    if (arg is None) or (len(arg) == 0):
        raise ValueError(msg)


def validate_date(date_text):
    try:
        datetime.datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Incorrect date format, should be YYYY-MM-DD")


def throw_if_false(condition, message):
    if not condition:
        raise ValueError(message)


# Parses metrics string into a list of metric executions
# E.g "Metric1#Metric2#Metric3" => ["Metric1", "Metric1#Metric2", "Metric1#Metric2#Metric3"]
def parse_metrics(metrics_name):
    sep = "#"
    metric = []
    arr = metrics_name.split(sep)

    if len(arr) != len(set(arr)):
        raise ValueError("Duplicated metrics are not allowed!")

    if sep in metrics_name:
        arr = metrics_name.split(sep)
        m = []
        for item in arr:
            m.append(item)
            metric.append(sep.join(m))
    else:
        metric.append(metrics_name)
    return metric


def get_ttl(ttl_days, start_date=datetime.datetime.today()):
    """Get ttl value epoch format to insert into DDB TTL field

    Arguments:
        ttl_days {int} -- Number of days to keep the record

    Keyword Arguments:
        start_date {datetime} -- Starting timestamp (default: {datetime.datetime.today()})

    Returns:
        int -- Value to insert into DynamoDB TTL field
    """
    ttl_date = start_date + datetime.timedelta(days=ttl_days)
    expiry_ttl = int(time.mktime(ttl_date.timetuple()))
    return expiry_ttl


def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False
