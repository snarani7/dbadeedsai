# dbadeeds.ai — AI-Powered Database Intelligence Platform

A Flask-based web application for database administration and AI-powered assistance. Supports Oracle and PostgreSQL databases with natural language querying, AI chat, and automated monitoring.

💡 Built on [Claude](https://www.anthropic.com/) by **sandeep reddy narani**.

## Features

- **AI-Powered Database Assistant**: Natural language queries to databases using LLMs
- **Multi-Database Support**: Oracle and PostgreSQL
- **Web Interface**: Modern Flask web app with responsive UI
- **User Management**: Role-based access control
- **Connection Management**: Secure database connection handling
- **AI Agents**: Specialized agents for performance monitoring and troubleshooting
- **API Endpoints**: RESTful API for integrations
- **Docker Support**: Containerized deployment

## Watch the overview video:

https://www.youtube.com/watch?v=cG_3XORJ8wY

## Quick Start

### Prerequisites

- Python 3.8+
- Oracle Instant Client (for Oracle support)
- PostgreSQL client libraries

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/dbadeedsai.git
   cd dbadeedsai
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy environment file:
   ```bash
   cp .env.example .env
   ```

4. Edit `.env` with your configuration:
   ```bash
   FLASK_ENV=development
   SECRET_KEY=your-secret-key
   OPENAI_API_KEY=sk-...
   ```

5. Run the application:
   ```bash
   python wsgi.py
   ```

Visit `http://localhost:5000` to access the web interface.

## Configuration

### Environment Variables

- `FLASK_ENV`: Set to `development` or `production`
- `SECRET_KEY`: Flask secret key for sessions
- `OPENAI_API_KEY`: OpenAI API key for AI features
- `ANTHROPIC_API_KEY`: Anthropic Claude API key (optional)
- `GOOGLE_API_KEY`: Google AI API key (optional)
- `GROQ_API_KEY`: Groq API key (optional)

### Database Connections

Add database connections in `data/db_connections.json`:

```json
{
  "oracle_1": {
    "name": "My Oracle DB",
    "db_type": "oracle",
    "connection_string": "user/password@host:1521/service",
    "is_active": true,
    "owner": "admin"
  }
}
```

## Usage

### Web Interface

- **Dashboard**: Overview of connections and recent activity
- **AI Assistant**: Chat with AI about your databases
- **Ask DBA**: Natural language database queries
- **Connections**: Manage database connections
- **Users**: User management (admin only)

### API

The application provides REST API endpoints documented at `/api/docs`.

## Docker Deployment

```bash
docker-compose up -d
```

## Development

### Project Structure

```
├── app/                    # Flask application
│   ├── api/               # API blueprints
│   ├── templates/         # Jinja2 templates
│   └── static/            # CSS/JS assets
├── data/                  # Configuration and data files
├── sql/                   # SQL scripts for Oracle/PostgreSQL
├── requirements.txt       # Python dependencies
└── wsgi.py               # Application entry point
```

### Running Tests

```bash
pytest
```

## Contributing

Contributions, issues, and feature requests are welcome!

📝 License
This project is licensed under the MIT License - see the LICENSE file for details.
Copyright (c) 2026 sandeep reddy narani

👤 Author
sandeep reddy narani

📮 Support
For issues, questions, or suggestions, please open an issue in the repository.
https://dbadeeds.com/dbadeeds-ai/

## Acknowledgments

- Built with Flask, SQLAlchemy, and various AI libraries
- Inspired by database administration tools and AI assistants

Note: This tool is designed for experienced database administrators and should be used with appropriate caution in production environments. Always verify AI-generated queries before execution on critical systems.
