from pydantic import BaseModel, Field
from cat.mad_hatter.decorators import plugin

class PluginSettings(BaseModel):
    sqlite_db_path: str = Field(
        default='sqlite:///cat/data/dietician.db',
        title="Sqlite filepath. Change it only if you know what you are doing!",
    )
    delete_db: bool = Field(
        default=False,
        title="Delete Database",
        description="Set to True to delete the database file. This action cannot be undone.",
    )

@plugin
def settings_model():
    return PluginSettings