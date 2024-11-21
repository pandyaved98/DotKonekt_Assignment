# Setup Instructions for RAG-based Blog Generation System

## Prerequisites
- Python 3.8 or higher
- NVIDIA GPU with at least 4GB VRAM (as per my personal system)
- MongoDB Atlas account
- Redis server
- OpenSearch server
- Llama 2/3/3.1/3.2 model access

## Environment Setup

1. **Clone the repository and create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  

# For Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Environment Variables Configuration**:
Create a `.env` file in the root directory and update these values:

```env
# Update these values according to your setup
SECRET_KEY=your-super-secure-secret-key-here
MONGO_URI=your-mongodb-atlas-uri
OPENSEARCH_PASSWORD=your-opensearch-password

# Update MODEL_PATH to your local Llama model path
MODEL_PATH=path/to/your/local/llama-model

# Keep these default values unless you have different configurations
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_USER=admin
REDIS_HOST=localhost
REDIS_PORT=6379
```

## Required Changes

1. **MongoDB Setup**:
- Create a MongoDB Atlas account
- Create a new cluster
- Get your connection string
- Replace `MONGO_URI` in `.env`

2. **Model Setup**:
- Download Llama 2 model
- Update `MODEL_PATH` in `.env` to point to your model location

3. **OpenSearch Setup**:
- Install OpenSearch locally or use cloud service
- Update OpenSearch credentials in `.env`

## API Endpoints

1. **User Authentication**:
```http
POST /register
Content-Type: application/json
{
    "username": "testuser",
    "email": "test@example.com",
    "password": "testpassword123"
}

POST /login
Content-Type: application/json
{
    "email": "test@example.com",
    "password": "testpassword123"
}
```

2. **Document Upload**:
```http
POST /upload
Headers:
    Authorization: Bearer <your_token>
Body:
    form-data
    Key: file
    Value: [Select PDF file]
```

3. **Blog Creation**:
```http
POST /create
Headers:
    Authorization: Bearer <your_token>
Content-Type: application/json
{
    "topic": "Your Blog Topic"
}
```

4. **Get Product Recommendations**:
```http
GET /products?blog_id=<blog_id>
Headers:
    Authorization: Bearer <your_token>
```

5. **Search Content**:
```http
GET /search?query=your search query
Headers:
    Authorization: Bearer <your_token>
```

## Response Formats

1. **Upload Response**:
```json
{
    "message": "Document processed successfully",
    "filename": "document.pdf",
    "chunks_processed": 10,
    "total_characters": 50000
}
```

2. **Blog Creation Response**:
```json
{
    "message": "Blog created successfully",
    "blog_id": "blog_id_here",
    "content": "Blog content here",
    "word_count": 800,
    "source_documents_used": 5
}
```

3. **Product Recommendations Response**:
```json
{
    "categories": ["category1", "category2", "category3"],
    "products": [
        {
            "id": "product_id",
            "name": "Product Name",
            "category": "Category"
        }
    ],
    "blog_topic": "Original Blog Topic"
}
```

Error responses include detailed messages:
```json
{
    "error": "Error description here"
}
```

## Running the Application

1. Start Redis server
2. Start OpenSearch server
3. Run the Flask application:
```bash
python app.py
```

The server will start on `http://localhost:5000`

## Notes
- Ensure all services (Redis, OpenSearch) are running before starting the application
- Monitor GPU memory usage when processing large documents
- Use proper token authentication for all protected endpoints
- PDF files should not exceed 16MB (configurable in .env)
