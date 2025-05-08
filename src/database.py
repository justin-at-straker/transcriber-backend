from dotenv import load_dotenv
from straker_utils.sql import DBEnginePool


load_dotenv()


engines = DBEnginePool(
    (
        "franchise",
        "memory_readonly",
        "sitecommons",
        "terminology",
        "translators_readonly",
        "segment_changes",
        "segments_log"
    ),
    dbapi="mysqlconnector",
    # echo=get_current_environment() == Environment.local,
)
