from flask import Blueprint, request, jsonify, current_app
from auth import token_required
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from database import vector_store, blogs_db, products_db, bulk_index_documents, search_documents, opensearch_client
import os
from datetime import datetime
from PyPDF2 import PdfReader
import io
from werkzeug.utils import secure_filename
from bson import ObjectId
import requests
from bs4 import BeautifulSoup
import logging
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

rag_bp = Blueprint('rag', __name__)

MODEL_PATH = r""

def initialize_model():
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_PATH,
            trust_remote_code=True,
            padding_side='left'
        )
        tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            device_map="auto",
            torch_dtype=torch.float16,
            trust_remote_code=True,
            load_in_8bit=True
        )

        pipe = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            max_length=2048,
            temperature=0.6,
            top_p=0.85,
            repetition_penalty=1.2,
            device_map="auto",
            pad_token_id=tokenizer.pad_token_id,
            no_repeat_ngram_size=3
        )

        return model, tokenizer, pipe

    except Exception as e:
        logger.error(f"Model initialization error: {str(e)}")
        raise

model, tokenizer, generator = initialize_model()

def process_pdf(file):
    try:
        pdf_stream = io.BytesIO(file.read())
        pdf_reader = PdfReader(pdf_stream)
        text = []
        for page in pdf_reader.pages:
            content = page.extract_text()
            if content:
                text.append(content)
        return "\n".join(text).strip()
    except Exception as e:
        logger.error(f"PDF processing error: {str(e)}")
        raise

def chunk_text(text: str, chunk_size: int = 1000):
    words = text.split()
    chunks = []
    current_chunk = []
    current_size = 0

    for word in words:
        word_size = len(word) + 1
        if current_size + word_size > chunk_size:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_size = word_size
        else:
            current_chunk.append(word)
            current_size += word_size

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks

def extract_search_terms(topic: str):
    common_words = {'and', 'or', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'about', 'explain', 'me'}
    terms = topic.lower().split()
    return [term for term in terms if term not in common_words]

def get_relevant_context(topic: str, limit: int = 5):
    try:
        search_query = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": topic,
                                "fields": ["content^3", "metadata.filename"],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                                "minimum_should_match": "30%"
                            }
                        },
                        {
                            "match": {
                                "content": {
                                    "query": topic,
                                    "operator": "or",
                                    "minimum_should_match": "2<70%"
                                }
                            }
                        }
                    ],
                    "minimum_should_match": 1
                }
            },
            "min_score": 0.1,
            "size": limit
        }

        results = opensearch_client.search(
            index="documents",
            body=search_query
        )

        context = []
        for hit in results['hits']['hits']:
            if 'content' in hit['_source']:
                context.append(hit['_source']['content'])

        return context
    except Exception as e:
        logger.error(f"Error getting context: {str(e)}")
        return []

def generate_blog_content(topic: str, context: List[str], target_words: int = 800):
    try:
        if not context:
            raise ValueError("No relevant context available")
            
        context_text = "\n".join(context)
        
        strict_prompt = f"""Based on ONLY the following context information, write about {topic}.
If you cannot find enough relevant information in the context, respond with 'INSUFFICIENT_CONTEXT'.

CONTEXT:
{context_text[:2000]}

RULES:
1. Use ONLY information from the context
2. Do not add external knowledge
3. Write exactly {target_words} words
4. Include technical details from context
5. Be specific and accurate
6. No general statements
7. Focus on factual content

Write the blog post:"""

        response = generator(
            strict_prompt,
            max_new_tokens=1500,
            do_sample=True,
            temperature=0.6,
            top_p=0.85,
            repetition_penalty=1.2,
            num_return_sequences=1
        )

        blog_content = response[0]['generated_text']
        
        if "INSUFFICIENT_CONTEXT" in blog_content:
            raise ValueError(f"Insufficient context available for topic: {topic}")

        blog_content = blog_content.split("Write the blog post:")[-1].strip()
        
        words = blog_content.split()
        if len(words) > target_words:
            blog_content = ' '.join(words[:target_words])
        elif len(words) < target_words:
            remaining = target_words - len(words)
            continuation_prompt = f"""Continue using ONLY the original context. DO NOT add new information.
Previous content: {blog_content}
Continue for {remaining} more words:"""
            
            additional = generator(
                continuation_prompt,
                max_new_tokens=remaining * 2,
                temperature=0.6
            )[0]['generated_text']
            
            blog_content = ' '.join((blog_content + " " + additional).split()[:target_words])

        return blog_content

    except Exception as e:
        logger.error(f"Error generating blog: {str(e)}")
        raise

@rag_bp.route('/upload', methods=['POST'])
@token_required
def upload_document(current_user):
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are allowed'}), 400

        filename = secure_filename(file.filename)

        text_content = process_pdf(file)
        if not text_content:
            return jsonify({'error': 'Could not extract text from PDF'}), 400

        chunks = chunk_text(text_content)
        
        metadata_list = [{
            "filename": filename,
            "chunk_id": i,
            "user_id": str(current_user['_id']),
            "upload_date": datetime.utcnow().isoformat(),
            "total_chunks": len(chunks),
            "content_type": "pdf"
        } for i in range(len(chunks))]

        indexed_count = bulk_index_documents(chunks, metadata_list)

        return jsonify({
            'message': 'Document processed successfully',
            'filename': filename,
            'chunks_processed': indexed_count,
            'total_characters': len(text_content)
        }), 201

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@rag_bp.route('/create', methods=['POST'])
@token_required
def create_blog(current_user):
    try:
        data = request.get_json()
        if not data or 'topic' not in data:
            return jsonify({'error': 'Topic is required'}), 400

        topic = data['topic']
        search_terms = extract_search_terms(topic)
        
        all_context = []
        for term in search_terms:
            context = get_relevant_context(term)
            all_context.extend(context)
        
        all_context = list(dict.fromkeys(all_context))
        
        if not all_context:
            return jsonify({
                'error': 'No relevant information found',
                'message': 'Cannot generate blog post as no relevant information is available in the knowledge base.'
            }), 404

        try:
            blog_content = generate_blog_content(topic, all_context)
        except ValueError as e:
            if "Insufficient context" in str(e):
                return jsonify({
                    'error': 'Insufficient context',
                    'message': 'Cannot generate blog post as the available information is not sufficient for this topic.'
                }), 404
            raise

        blog = {
            'topic': topic,
            'content': blog_content,
            'author_id': current_user['_id'],
            'created_at': datetime.utcnow(),
            'word_count': len(blog_content.split()),
            'source_documents': len(all_context)
        }
        
        result = blogs_db.blogs.insert_one(blog)

        metadata = {
            "type": "blog",
            "blog_id": str(result.inserted_id),
            "author_id": str(current_user['_id']),
            "timestamp": datetime.utcnow().isoformat(),
            "topic": topic
        }
        
        bulk_index_documents([blog_content], [metadata])

        return jsonify({
            'message': 'Blog created successfully',
            'blog_id': str(result.inserted_id),
            'content': blog_content,
            'word_count': len(blog_content.split()),
            'source_documents_used': len(all_context)
        }), 201

    except Exception as e:
        logger.error(f"Blog creation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@rag_bp.route('/products', methods=['GET'])
@token_required
def get_products(current_user):
    try:
        blog_id = request.args.get('blog_id')
        if not blog_id:
            return jsonify({'error': 'Blog ID is required'}), 400

        blog = blogs_db.blogs.find_one({'_id': ObjectId(blog_id)})
        if not blog:
            return jsonify({'error': 'Blog not found'}), 404

        prompt = f"""Based on this blog about '{blog['topic']}', suggest 5 specific product categories.
Blog content: {blog['content'][:500]}...

Requirements:
- List only product category names
- One per line
- Focus on practical items
- Must be relevant to topic

Categories:"""

        response = generator(
            prompt,
            max_new_tokens=100,
            temperature=0.3,
            num_return_sequences=1
        )
        
        categories = [
            cat.strip() 
            for cat in response[0]['generated_text'].split('\n') 
            if cat.strip() and not cat.startswith(("Based", "Categories", "Requirements", "Blog"))
        ][:5]

        products = list(products_db.products.find({
            '$or': [
                {'category': {'$in': categories}},
                {'tags': {'$in': categories}}
            ]
        }).limit(10))

        for product in products:
            product['_id'] = str(product['_id'])

        return jsonify({
            'categories': categories,
            'products': products,
            'blog_topic': blog['topic']
        })

    except Exception as e:
        logger.error(f"Product recommendation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@rag_bp.route('/search', methods=['GET'])
@token_required
def search_content(current_user):
    try:
        query = request.args.get('query', '')
        if not query:
            return jsonify({'error': 'Query parameter is required'}), 400

        results = search_documents(
            query,
            filters=[{
                "term": {
                    "metadata.user_id": str(current_user['_id'])
                }
            }]
        )

        return jsonify({
            'results': results,
            'total': len(results)
        })

    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def cleanup_gpu_memory():
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

@rag_bp.before_request
def before_request():
    cleanup_gpu_memory()