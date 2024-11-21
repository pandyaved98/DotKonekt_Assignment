# database.py
from pymongo import MongoClient
import redis
from opensearchpy import OpenSearch, helpers
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain_community.embeddings import HuggingFaceEmbeddings
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

mongo_client = MongoClient('')
products_db = mongo_client.products
blogs_db = mongo_client.blogs
users_db = mongo_client.users

redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=0,
    decode_responses=True
)

OPENSEARCH_INDEX = "documents"
OPENSEARCH_MAPPING = {
    "mappings": {
        "properties": {
            "content": {"type": "text"},
            "vector_field": {"type": "knn_vector", "dimension": 384},
            "metadata": {
                "type": "object",
                "properties": {
                    "filename": {"type": "keyword"},
                    "chunk_id": {"type": "integer"},
                    "user_id": {"type": "keyword"},
                    "upload_date": {"type": "date"},
                    "content_type": {"type": "keyword"},
                    "category": {"type": "keyword"}
                }
            }
        }
    },
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
            "number_of_shards": 1,
            "number_of_replicas": 1
        }
    }
}

opensearch_client = OpenSearch(
    hosts=[{
        'host': os.getenv('OPENSEARCH_HOST', 'localhost'),
        'port': int(os.getenv('OPENSEARCH_PORT', 9200))
    }],
    http_auth=(
        os.getenv('OPENSEARCH_USER', 'admin'),
        os.getenv('OPENSEARCH_PASSWORD', '')
    ),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False,
    timeout=30,
    max_retries=3,
    retry_on_timeout=True
)

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-mpnet-base-v2",
    model_kwargs={
        'device': 'cuda',
        'trust_remote_code': True
    },
    encode_kwargs={
        'normalize_embeddings': True,
        'batch_size': 8
    }
)

def ensure_opensearch_index():
    """Create OpenSearch index if it doesn't exist"""
    try:
        if not opensearch_client.indices.exists(OPENSEARCH_INDEX):
            logger.info(f"Creating OpenSearch index: {OPENSEARCH_INDEX}")
            response = opensearch_client.indices.create(
                index=OPENSEARCH_INDEX,
                body=OPENSEARCH_MAPPING
            )
            logger.info(f"Index created successfully: {response}")
            return True
        return True
    except Exception as e:
        logger.error(f"Error creating OpenSearch index: {str(e)}")
        raise

def bulk_index_documents(documents, metadata_list):
    """Bulk index documents with their embeddings"""
    try:
        embeddings_list = embeddings.embed_documents(documents)
        
        actions = []
        for doc, embed, meta in zip(documents, embeddings_list, metadata_list):
            action = {
                "_index": OPENSEARCH_INDEX,
                "_source": {
                    "content": doc,
                    "vector_field": embed,
                    "metadata": meta
                }
            }
            actions.append(action)
        
        if actions:
            success, errors = helpers.bulk(
                opensearch_client, 
                actions, 
                raise_on_error=False,
                raise_on_exception=False
            )
            
            if errors:
                logger.warning(f"Some documents failed to index: {errors}")
            
            logger.info(f"Successfully indexed {success} documents")
            return success
            
        return 0
        
    except Exception as e:
        logger.error(f"Error in bulk indexing: {str(e)}")
        raise

def initialize_vector_store():
    """Initialize OpenSearch vector store"""
    try:
        ensure_opensearch_index()
        return OpenSearchVectorSearch(
            opensearch_url=f"https://{os.getenv('OPENSEARCH_HOST', 'localhost')}:{os.getenv('OPENSEARCH_PORT', '9200')}",
            index_name=OPENSEARCH_INDEX,
            embedding_function=embeddings,
            http_auth=(
                os.getenv('OPENSEARCH_USER', 'admin'),
                os.getenv('OPENSEARCH_PASSWORD', 'Ved%40nt%40981204')
            ),
            use_ssl=True,
            verify_certs=False,
            ssl_show_warn=False
        )
    except Exception as e:
        logger.error(f"Error initializing vector store: {str(e)}")
        raise

vector_store = initialize_vector_store()

def search_documents(query, filters=None, limit=5):
    """Search documents with optional filters"""
    try:
        search_body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "content": query
                            }
                        }
                    ]
                }
            }
        }

        if filters:
            search_body["query"]["bool"]["filter"] = filters

        response = opensearch_client.search(
            index=OPENSEARCH_INDEX,
            body=search_body
        )

        return response['hits']['hits']
    except Exception as e:
        logger.error(f"Error searching documents: {str(e)}")
        raise

def delete_document(doc_id):
    """Delete a document from OpenSearch"""
    try:
        response = opensearch_client.delete(
            index=OPENSEARCH_INDEX,
            id=doc_id
        )
        return response['result'] == 'deleted'
    except Exception as e:
        logger.error(f"Error deleting document: {str(e)}")
        raise

def cleanup_old_documents(days=30):
    """Clean up documents older than specified days"""
    try:
        response = opensearch_client.delete_by_query(
            index=OPENSEARCH_INDEX,
            body={
                "query": {
                    "range": {
                        "metadata.upload_date": {
                            "lt": f"now-{days}d"
                        }
                    }
                }
            }
        )
        return response['deleted']
    except Exception as e:
        logger.error(f"Error cleaning up old documents: {str(e)}")
        raise