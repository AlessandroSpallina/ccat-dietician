import sqlite3
import os
from typing import List
from cat.log import log
from cat.mad_hatter.decorators import tool, hook
from pydantic import BaseModel
from langchain.indexes import SQLRecordManager, index
from langchain.docstore.document import Document
from langchain.vectorstores import Qdrant

# TODO: use settings instead of hard coded db path
# class DietSettings(BaseModel):
#     sqlite_file_path: str = "/app/cat/plugins/ccat-dietician/diet.db"


# @hook
# def plugin_settings_schema():   
#     return DietSettings.schema()


# Hook called when a list of Document is going to be inserted in memory from the rabbit hole.
# Here you can edit/summarize the documents before inserting them in memory
# Should return a list of documents (each is a langchain Document)
@hook
def before_rabbithole_stores_documents(docs: List[Document], cat) -> List[Document]:
    """Hook into the memory insertion pipeline.

    Allows modifying how the list of `Document` is inserted in the vector memory.

    For example, this hook is a good point to summarize the incoming documents and save both original and
    summarized contents.
    An official plugin is available to test this procedure.

    Parameters
    ----------
    docs : List[Document]
        List of Langchain `Document` to be edited.
    cat: CheshireCat
        Cheshire Cat instance.

    Returns
    -------
    docs : List[Document]
        List of edited Langchain documents.

    """

    vector_db = cat.memory.vectors.vector_db
    embedder = cat.embedder
    
    q = Qdrant(vector_db, "declarative", embedder)

    record_manager = SQLRecordManager(
        namespace="qdrant/declarative",
        db_url="sqlite:////app/cat/plugins/ccat-dietician/diet.db"
    )

    record_manager.create_schema()

    ret = index(
        docs,
        record_manager,
        q,
        delete_mode="incremental",
        source_id_key="source"
    )

    log(f"Dietist: index return is {ret}", "DEBUG")

    return []
