# dbadeeds.ai

> AI-Powered Oracle Database Management Assistant

**dbadeeds.ai** is an autonomous AI DBA assistant designed for Support Desk teams during alerts and incidents. It helps navigate and manage Oracle databases using AI, performing diagnostics, executing operational playbooks, and answering database-related questions in real time — safely and intelligently.

## 🚀 Features

- **🤖 AI Assistant**: Natural language interface powered by Google Gemini 2.5 Flash for database queries and assistance
- **🔌 Database Explorer**: Connect to Oracle databases (PDB/CDB) and execute SQL queries interactively
- **⚙️ DBA Playbooks**: Pre-built SQL scripts for common database administration tasks
- **📊 Dashboard**: Real-time database health metrics and overview
- **🛡️ Safe Operations**: Intelligent AI agent that understands Oracle environment context

## 📋 Prerequisites

- Python 3.8 or higher
- Oracle Database (PDB or CDB)
- Access to Oracle database credentials
- Google Gemini API key (for AI Assistant functionality)

## 📦 Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd DBGPT
   ```

2. **Install required Python packages**
   ```bash
   pip install streamlit pandas oracledb streamlit-aggrid langchain langchain-openai
   ```

   Or using `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Oracle Client** (if needed)
   - The application uses `python-oracledb` in thin mode, which doesn't require Oracle Instant Client
   - For thick mode, install Oracle Instant Client separately

## ⚙️ Configuration

### API Key Setup

1. **OpenAPI Key**:
   - openai_api_key="YOUR_OPEN_API_KEY"
   - Update `app.py` line 87 with your API key:
   ```python
   
2. **Google Gemini API Key**:
   - Get your API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
   - Update `app.py` line 87 with your API key:
   ```python
   openai_api_key="YOUR_GEMINI_API_KEY"
   enable googleai URL
   ```

### Database Connection

The application supports two connection modes:

1. **Testing Mode** (default): Uses hard-coded test credentials
   ```python
   TEST_USER = "system"
   TEST_PASS = "oracle"
   TEST_DSN = "localhost:1521/freepdb1"
   ```

2. **Dynamic Mode**: Enter database credentials through the UI

### Buddy Tool Configuration

The application integrates with a shell script tool. Update the path in `app.py` line 28:
```python
script = "/dbadeeeds/script/oradbabuddy.sh"
```

## 🎯 Usage

### Starting the Application

```bash
streamlit run app.py
```

The application will open in your default web browser at `http://localhost:8501`

### Application Modes

#### 1. **Dashboard**
- View database overview and health metrics
- Monitor active sessions and long-running queries
- Get insights about how dbadeeds.ai works

#### 2. **Database Explorer**
- Connect to Oracle databases
- Test database connections
- Execute custom SQL queries
- View query results in interactive dataframes

#### 3. **AI Assistant**
- Ask natural language questions about your database
- Examples:
  - "Show me long running queries for the last hour"
  - "What is the status of my PDB?"
  - "Find blocking sessions"

#### 4. **DBA Playbooks**
Each database is different from customer to customer and you want to control AI which your custom queries and you can able to achive using Playbooks
Pre-built SQL scripts for common tasks:
- Long Running SQLs
- SQL Monitoring
- Blocking Sessions
- Invalid Objects
- Unusable Indexes
- Failed Jobs
- Datapump Jobs
- Database Size
- Tablespace Usage
- And more...

## 📁 Project Structure

```
DBGPT/
├── app.py                 # Main Streamlit application
├── LICENSE               # MIT License
├── README.md             # This file
└── sql/                  # SQL playbook files
    ├── long_running_sqls.sql
    ├── pdb_status.sql
    └── sql_monitoring.sql
```

## 🔧 Dependencies

- **streamlit**: Web application framework
- **pandas**: Data manipulation and analysis
- **oracledb**: Oracle database connectivity
- **streamlit-aggrid**: Interactive data grids
- **langchain**: AI agent framework
- **langchain-openai**: LangChain OpenAI integration (used with Gemini API)

## 🔒 Security Notes

- ⚠️ **Never commit API keys or database credentials to version control**
- Use environment variables or secure configuration files for sensitive data
- The application is designed for internal use and should not be exposed to public networks without proper security measures

## 🛠️ How It Works

1. **Connect**: Securely connect to your Oracle database (PDB / CDB)
2. **Observe**: Collect metadata, performance signals, and runtime stats
3. **Reason**: AI agent understands context using DBA logic
4. **Act**: Executes safe SQL or playbooks, or guides the DBA with insights

## 💡 Why Use dbadeeds.ai?

- ⚙️ **Reduce MTTR** during production incidents
- 📊 **Eliminate repetitive** health-check SQLs
- 🧠 **Augment junior DBAs** with senior-level intelligence
- 🚨 **Catch problems** before users feel them

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Copyright (c) 2024 sandeep reddy narani

## 👤 Author

**sandeep reddy narani**

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

## 📮 Support

For issues, questions, or suggestions, please open an issue in the repository.

---

**Note**: This tool is designed for experienced database administrators and should be used with appropriate caution in production environments. Always verify AI-generated queries before execution on critical systems.

