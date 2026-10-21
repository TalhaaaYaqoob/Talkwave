from api.db.base_client import _shared_engine, _shared_session_factory

engine = _shared_engine
async_session = _shared_session_factory
