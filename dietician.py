import hashlib
import os
import json
from typing import List
from cat.log import log
from cat.mad_hatter.decorators import hook, plugin
from langchain.docstore.document import Document
from sqlalchemy import ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session
from cat.looking_glass.stray_cat import StrayCat


class Base(DeclarativeBase):
    pass


class DietDocument(Base):
    __tablename__= 'document'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    
    chunks: Mapped[List["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


    def __repr__(self) -> str:
        return f'DietDocument(name={self.name!r}, hash={self.hash!r})'


class Chunk(Base):
    __tablename__ = 'chunk'
    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_count: Mapped[int]
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"))

    document: Mapped["DietDocument"] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f'Chunk(chunk_count={self.chunk_count!r})'


# sqlalchemy sqlite engine
engine = None
# Base.metadata.create_all(engine, checkfirst=True)
# log.warning(f"Dietician is using a sqlite file located here: {DEFAULT_SQLITE_FILEPATH}. You can change the path in the plugin settings.")


@hook(priority=10)
def before_rabbithole_splits_text(doc, cat):
    # doc is a list with only one element, always
    cat.working_memory.ccat_dietician = {
        'name': doc[0].metadata['source'],
        'hash': hashlib.sha256(doc[0].page_content.encode()).hexdigest()
    }

    global engine
    db_filepath = cat.mad_hatter.get_plugin().load_settings()["sqlite_db_path"]
    engine = create_engine(db_filepath)
    Base.metadata.create_all(engine, checkfirst=True)
    log.debug(f"Dietician is writing on the sqlite db located here: {db_filepath}. You can change the path in the plugin settings.")


    return doc


@hook(priority=10)
def before_rabbithole_stores_documents(docs: List[Document], cat) -> List[Document]:
    cat.working_memory.ccat_dietician['chunk_count'] = len(docs)

    with Session(engine) as session:
        try:
            doc_by_name = session.query(DietDocument).filter_by(name=cat.working_memory.ccat_dietician['name']).first()
            if doc_by_name is None:
                doc_by_hash = session.query(DietDocument).filter_by(hash=cat.working_memory.ccat_dietician['hash']).first()
                if doc_by_hash is None:
                        db_doc = DietDocument(name=cat.working_memory.ccat_dietician['name'], hash=cat.working_memory.ccat_dietician['hash'], chunks=[Chunk(chunk_count=cat.working_memory.ccat_dietician['chunk_count'])])
                        session.add(db_doc)
                        session.commit()
                        log.info(f"Dietician is allowing the ingestion of a new document: {db_doc}")
                        return docs
                else:
                    if cat.working_memory.ccat_dietician['chunk_count'] in [c.chunk_count for c in doc_by_hash.chunks]:
                        log.info(f"Dietician detected {cat.working_memory.ccat_dietician['name']} as a duplicate of {doc_by_hash.name}, since the number of chunks ({cat.working_memory.ccat_dietician['chunk_count']}) coincides to what is already in declarative memory, this ingestion is going to be avoided.")
                        return []
                    else:
                        doc_by_hash.chunks.append(Chunk(chunk_count=cat.working_memory.ccat_dietician['chunk_count']))
                        session.add(doc_by_hash)
                        session.commit()
                        log.info(f"Dietician detected {cat.working_memory.ccat_dietician['name']} as a duplicate of {doc_by_hash.name}, since the number of chunks ({cat.working_memory.ccat_dietician['chunk_count']}) produced now is different from what is already in declarative memory, this ingestion is going to be allowed.")
                        return docs
            else:
                if cat.working_memory.ccat_dietician['hash'] == doc_by_name.hash:
                    if cat.working_memory.ccat_dietician['chunk_count'] in [c.chunk_count for c in doc_by_name.chunks]:
                        log.info(f"Dietician detected that {doc_by_name.name} was already ingested, since the number of chunks ({cat.working_memory.ccat_dietician['chunk_count']}) coincides to what is already in declarative memory, this ingestion is going to be avoided.")
                        return []
                    else:
                        doc_by_name.chunks.append(Chunk(chunk_count=cat.working_memory.ccat_dietician['chunk_count']))
                        session.add(doc_by_name)
                        session.commit()
                        log.info(f"Dietician detected that {doc_by_name.name} was already ingested, since the number of chunks ({cat.working_memory.ccat_dietician['chunk_count']}) produced now is different from what is already in declarative memory, this ingestion is going to be allowed.")
                        return docs
                else:
                    old_chunks, _ = cat.memory.vectors.declarative.client.scroll(
                        collection_name=cat.memory.vectors.declarative.collection_name,
                        scroll_filter=cat.memory.vectors.declarative._qdrant_filter_from_dict({'source': doc_by_name.name}),
                        with_payload=True
                    )
                    old_chunks_text = [c.payload['page_content'] for c in old_chunks]
                    new_chunks_text = [d.page_content for d in docs]
                    
                    # we have to delete all chunks in declarative memory that are not in the new document because those chunks are related an old version of the document
                    old_chunks_to_delete_ids = [c.id for c in old_chunks if c.payload['page_content'] not in new_chunks_text]

                    if len(old_chunks_to_delete_ids) > 0:
                        cat.memory.vectors.declarative.delete_points(old_chunks_to_delete_ids)

                    log.info(f"Dietician detected an hash change for the document {doc_by_name}, this means that the document has beed updated. Allowing the ingestion of new chunks and deleting all the old chunks not any more present in the current document version.")
                    
                    # docs contain only chunks never inserted in declarative memory, we keep into the vectordb any chunk previously inserted (to avoid unnecessary calls to the embedding model)
                    return [d for d in docs if d.page_content not in old_chunks_text]

        except Exception as e:
            session.rollback()
            log.error(f"Something weird happened: {str(e)}. Dietician is preventing the ingestion of {cat.working_memory.ccat_dietician['name']}")
            return []


def remove_documents_by_metadata(cat, metadata_filter: dict, exclude_metadata: dict = None, exclude_sources: list = None, qdrant_limit: int = 10000) -> dict:
    """
    Generic function to remove documents from both dietician database and vector memory
    based on metadata filtering.
    
    Args:
        cat: The StrayCat instance
        metadata_filter: Dictionary of metadata key-value pairs to match for removal
        exclude_metadata: Optional dictionary of metadata to exclude from removal
        exclude_sources: Optional list of source URLs to exclude from removal (for pages that were scraped but not re-ingested)
        
    Returns:
        dict: Summary of removal operations with counts and details
    """
    global engine
    
    if engine is None:
        db_filepath = cat.mad_hatter.get_plugin().load_settings()["sqlite_db_path"]
        engine = create_engine(db_filepath)
        Base.metadata.create_all(engine, checkfirst=True)
    
    removed_count = 0
    vector_removed_count = 0
    errors = []
    removed_urls = []
    
    try:
        # Find chunks in vector memory that match the filter criteria
        all_chunks, _ = cat.memory.vectors.declarative.client.scroll(
            collection_name=cat.memory.vectors.declarative.collection_name,
            scroll_filter=cat.memory.vectors.declarative._qdrant_filter_from_dict(metadata_filter),
            with_payload=True,
            limit=qdrant_limit
        )
        
        chunks_to_remove = []
        urls_to_remove_from_db = set()
        
        for chunk in all_chunks:
            should_remove = True
            
            # Get metadata from chunk payload (it's nested under 'metadata' key)
            chunk_metadata = chunk.payload.get('metadata', {})
            chunk_source = chunk_metadata.get('source')
            
            # Check if source is in the exclude_sources list (pages that were scraped, even if not re-ingested)
            if exclude_sources and chunk_source in exclude_sources:
                should_remove = False
                log.debug(f"Chunk {chunk.id} excluded from removal - source {chunk_source} is in scraped pages list")
            
            # Check if chunk should be excluded based on exclude_metadata
            if should_remove and exclude_metadata:
                for key, value in exclude_metadata.items():
                    chunk_value = chunk_metadata.get(key)
                    if chunk_value == value:
                        should_remove = False
                        log.debug(f"Chunk {chunk.id} excluded from removal - {key}={chunk_value} matches exclude filter")
                        break
            
            if should_remove:
                chunks_to_remove.append(chunk.id)
                if chunk_source:
                    urls_to_remove_from_db.add(chunk_source)
                    if chunk_source not in removed_urls:
                        removed_urls.append(chunk_source)
                log.debug(f"Chunk {chunk.id} marked for removal - source: {chunk_source}, metadata: {chunk_metadata}")
        
        # Remove chunks from vector memory
        if chunks_to_remove:
            cat.memory.vectors.declarative.delete_points(chunks_to_remove)
            vector_removed_count = len(chunks_to_remove)
            log.info(f"Removed {vector_removed_count} chunks from vector memory based on metadata filter")
        
        # Remove corresponding documents from dietician database
        with Session(engine) as session:
            for url in urls_to_remove_from_db:
                try:
                    doc_to_remove = session.query(DietDocument).filter_by(name=url).first()
                    if doc_to_remove:
                        # Delete all associated chunks first to avoid foreign key constraint issues
                        for chunk in doc_to_remove.chunks:
                            session.delete(chunk)
                        # Now delete the document
                        session.delete(doc_to_remove)
                        removed_count += 1
                        log.info(f"Removed document and its chunks from dietician database: {url}")
                except Exception as e:
                    error_msg = f"Error removing document {url} from database: {str(e)}"
                    log.error(error_msg)
                    errors.append(error_msg)
            
            # Commit all database changes
            session.commit()
            
    except Exception as e:
        error_msg = f"Metadata-based cleanup operation failed: {str(e)}"
        log.error(error_msg)
        errors.append(error_msg)
    
    result = {
        "removed_count": removed_count,
        "vector_removed_count": vector_removed_count,
        "removed_urls": removed_urls,
        "errors": errors
    }
    
    log.info(f"Metadata-based cleanup completed: {result}")
    return result


def save_plugin_settings_to_file(settings: dict, plugin_path: str) -> dict:
    """
    Save plugin settings to settings.json file in the plugin directory.
    This replicates the default save behavior from the Cat framework.
    
    Args:
        settings: The settings dictionary to save
        plugin_path: The path to the plugin directory
        
    Returns:
        The updated settings dictionary, or empty dict if save failed
    """
    settings_file_path = os.path.join(plugin_path, "settings.json")
    
    # Load already saved settings (replicate load_settings behavior)
    old_settings = {}
    if os.path.exists(settings_file_path):
        try:
            with open(settings_file_path, "r") as json_file:
                old_settings = json.load(json_file)
        except Exception as e:
            log.error(f"Unable to load existing settings: {e}")
    
    # Merge new settings with old ones
    updated_settings = {**old_settings, **settings}
    
    # Save settings to file
    try:
        with open(settings_file_path, "w") as json_file:
            json.dump(updated_settings, json_file, indent=4)
        return updated_settings
    except Exception as e:
        log.error(f"Unable to save plugin settings: {e}")
        return {}


@plugin
def save_settings(settings):
    """Handle plugin settings save with optional database deletion."""
    delete_db = settings.get("delete_db", False)
    
    if delete_db:
        db_path = settings.get("sqlite_db_path", "sqlite:///cat/data/dietician.db")
        
        # Extract file path from SQLAlchemy connection string
        if db_path.startswith("sqlite:///"):
            file_path = db_path[10:]  # Remove "sqlite:///" prefix
        else:
            file_path = db_path
            
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                log.info(f"Dietician: Successfully deleted database file: {file_path}")
            else:
                log.warning(f"Dietician: Database file does not exist: {file_path}")
        except Exception as e:
            log.error(f"Dietician: Failed to delete database file {file_path}: {str(e)}")
        
        # Reset the delete_db flag to False after attempting deletion
        settings["delete_db"] = False
    
    # Save settings using the extracted function (replicates default Cat behavior)
    plugin_path = os.path.dirname(os.path.abspath(__file__))
    return save_plugin_settings_to_file(settings, plugin_path)