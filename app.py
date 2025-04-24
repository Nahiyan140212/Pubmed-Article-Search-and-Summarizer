import os
import re
import time
import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="PubMedSearch - PubMed Article Search and Summarizer",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Handle both local development and Streamlit Cloud deployment
if 'OPENAI_API_KEY' in os.environ:
    # Local development with .env file
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
else:
    # Streamlit Cloud with secrets
    api_key = st.secrets["OPENAI_API_KEY"]

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #0083B8;
        text-align: center;
        margin-bottom: 0;
        font-weight: 700;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #555;
        text-align: center;
        margin-bottom: 30px;
        font-style: italic;
    }
    .result-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
        border-left: 5px solid #0083B8;
    }
    .article-title {
        font-size: 1.3rem;
        font-weight: 600;
        color: #0083B8;
        margin-bottom: 10px;
    }
    .article-meta {
        font-size: 0.9rem;
        color: #666;
        margin-bottom: 10px;
    }
    .article-abstract {
        font-size: 1rem;
        margin-bottom: 15px;
    }
    .article-summary {
        background-color: #f0f7fb;
        padding: 15px;
        border-radius: 5px;
        border-left: 3px solid #0083B8;
        margin-bottom: 15px;
    }
    .metrics-card {
        background-color: #f0f7fb;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
        margin-bottom: 15px;
    }
    .metrics-value {
        font-size: 2rem;
        font-weight: 700;
        color: #0083B8;
    }
    .metrics-label {
        font-size: 0.9rem;
        color: #555;
    }
    .qa-box {
        background-color: #f0f7fb;
        padding: 20px;
        border-radius: 10px;
        margin-top: 20px;
    }
    .tab-content {
        padding: 15px 0;
    }
    .alert-info {
        background-color: #e2f0fd;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 15px;
    }
    .filter-section {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    .badge {
        background-color: #0083B8;
        color: white;
        padding: 3px 10px;
        border-radius: 15px;
        font-size: 0.8rem;
        margin-right: 5px;
    }
    .loading-spinner {
        text-align: center;
        padding: 20px;
    }
    .sample-search {
        background-color: #f8f9fa;
        border: 1px solid #ddd;
        border-radius: 5px;
        padding: 15px;
        margin-bottom: 10px;
        cursor: pointer;
        transition: all 0.3s;
    }
    .sample-search:hover {
        background-color: #e2f0fd;
        border-color: #0083B8;
    }
    .footer {
        text-align: center;
        margin-top: 30px;
        padding-top: 20px;
        border-top: 1px solid #eee;
        font-size: 0.8rem;
        color: #666;
    }
</style>
""", unsafe_allow_html=True)

# Functions for PubMed API interaction
def build_pubmed_query(keywords, disease=None, year_range=None, author=None, journal=None, logic_operator="AND"):
    """Build a query string for PubMed using various filters."""
    
    # Process keywords
    keywords_str = " ".join(f'"{kw}"' for kw in keywords if kw.strip())
    
    # Start building query components
    query_parts = []
    
    if keywords_str:
        query_parts.append(f"({keywords_str})")
    
    if disease and disease.strip():
        query_parts.append(f'("{disease}"[MeSH Terms] OR "{disease}"[All Fields])')
    
    # Add year range if provided
    if year_range and len(year_range) == 2:
        start_year, end_year = year_range
        query_parts.append(f"({start_year}[PDAT]:{end_year}[PDAT])")
    
    # Add author if provided
    if author and author.strip():
        query_parts.append(f'"{author}"[Author]')
    
    # Add journal if provided
    if journal and journal.strip():
        query_parts.append(f'"{journal}"[Journal]')
    
    # Join all parts with the selected operator
    final_query = f" {logic_operator} ".join(query_parts)
    
    return final_query

def fetch_pubmed_count(query):
    """Fetch the total number of results for a query from PubMed."""
    headers = {"User-Agent": "Mozilla/5.0"}
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json"
    }
    
    try:
        search_response = requests.get(search_url, params=search_params, headers=headers, timeout=10).json()
        count = int(search_response["esearchresult"]["count"])
        return count
    except Exception as e:
        st.error(f"Error fetching result count: {e}")
        return 0

def parse_author_data(author):
    """Helper function to extract author names from the author tag."""
    last_name = author.find("lastname")
    fore_name = author.find("forename")
    initials = author.find("initials")
    collective_name = author.find("collectivename")
    
    # Handle collective author names (organizations, groups, etc.)
    if collective_name:
        return collective_name.get_text(strip=True)
    
    # Try to construct name from lastname and forename/initials
    if last_name:
        last = last_name.get_text(strip=True)
        
        if fore_name:
            fore = fore_name.get_text(strip=True)
            return f"{fore} {last}"
        elif initials:
            init = initials.get_text(strip=True)
            return f"{init} {last}"
        else:
            return last
    
    # Fallback to empty string if no identifiable name parts
    return ""

def fetch_pubmed_articles(query, max_results=5, use_mock_if_empty=False):
    """Fetch articles from PubMed based on the query and return detailed information."""
    headers = {"User-Agent": "Mozilla/5.0"}

    # Step 1: Search PubMed
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json"
    }
    try:
        with st.spinner("Searching PubMed database..."):
            search_response = requests.get(search_url, params=search_params, headers=headers, timeout=10).json()
            id_list = search_response["esearchresult"]["idlist"]
            
            if not id_list:
                if use_mock_if_empty:
                    st.warning("No articles found. Showing simulated data.")
                    return generate_mock_data()
                return []

            ids = ",".join(id_list)

        # Step 2: Fetch article summaries
        with st.spinner("Retrieving article details..."):
            fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            fetch_params = {
                "db": "pubmed",
                "id": ids,
                "retmode": "xml"
            }
            fetch_response = requests.get(fetch_url, params=fetch_params, headers=headers, timeout=10)
            soup = BeautifulSoup(fetch_response.text, "lxml")
            articles_xml = soup.find_all("pubmedarticle")

            articles_info = []
            for article, pmid in zip(articles_xml, id_list):
                title_tag = article.find("articletitle")
                abstract_tag = article.find("abstract")
                author_list_tag = article.find("authorlist")
                journal_tag = article.find("journal")
                keywords_tag = article.find_all("keyword")
                
                # Publication date - try different possible locations
                pub_date_tag = article.find("pubdate")
                if not pub_date_tag:
                    article_date = article.find("articledate")
                    if article_date:
                        pub_date_tag = article_date
                
                # Title
                title = title_tag.get_text(strip=True) if title_tag else "No title"

                # Abstract
                abstract = ""
                if abstract_tag:
                    # Handle structured abstracts with sections
                    abstract_sections = abstract_tag.find_all("abstracttext")
                    if abstract_sections:
                        for section in abstract_sections:
                            label = section.get("label")
                            if label:
                                abstract += f"{label}: "
                            abstract += f"{section.get_text(strip=True)} "
                    else:
                        abstract = abstract_tag.get_text(strip=True)
                else:
                    abstract = "No abstract available"

                # Authors
                authors = []
                if author_list_tag:
                    author_tags = author_list_tag.find_all("author")
                    for author in author_tags:
                        author_name = parse_author_data(author)
                        if author_name:
                            authors.append(author_name)
                
                if not authors:
                    authors = ["No authors listed"]

                # Journal
                journal_name = "Unknown Journal"
                if journal_tag:
                    journal_title = journal_tag.find("title")
                    if journal_title:
                        journal_name = journal_title.get_text(strip=True)
                    else:
                        isoabbreviation = journal_tag.find("isoabbreviation")
                        if isoabbreviation:
                            journal_name = isoabbreviation.get_text(strip=True)

                # Keywords
                keywords = [kw.get_text(strip=True) for kw in keywords_tag] if keywords_tag else []
                
                # Try to extract MeSH terms if no keywords
                if not keywords:
                    mesh_terms = article.find_all("meshheading")
                    if mesh_terms:
                        for mesh in mesh_terms[:5]:  # Limit to first 5
                            descriptor = mesh.find("descriptorname")
                            if descriptor:
                                keywords.append(descriptor.get_text(strip=True))

                # Publication Date
                pub_date = "No date"
                if pub_date_tag:
                    year = pub_date_tag.find("year")
                    month = pub_date_tag.find("month")
                    day = pub_date_tag.find("day")
                    
                    if year and month and day:
                        pub_date = f"{month.get_text()} {day.get_text()}, {year.get_text()}"
                    elif year and month:
                        pub_date = f"{month.get_text()} {year.get_text()}"
                    elif year:
                        pub_date = year.get_text()

                # PubMed Article URL
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

                articles_info.append({
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "publication_date": pub_date,
                    "journal": journal_name,
                    "keywords": keywords,
                    "article_url": url,
                    "pmid": pmid
                })

            return articles_info

    except Exception as e:
        st.error(f"Error during PubMed fetch: {e}")
        if use_mock_if_empty:
            st.warning("An error occurred. Showing simulated data.")
            return generate_mock_data()
        else:
            return []

def generate_mock_data():
    """Generate mock data for demonstration purposes."""
    current_year = datetime.now().year
    
    mock_articles = [
        {
            "title": "Recent Advances in Treatment Approaches for Autoimmune Disorders",
            "abstract": "This comprehensive review examines the latest therapeutic approaches for autoimmune disorders, focusing on targeted immunomodulators and personalized medicine strategies. We analyze clinical trials data from the past five years and discuss emerging treatment paradigms.",
            "authors": ["Sarah J. Wilson", "Michael Chang", "Priya Patel"],
            "publication_date": f"January {current_year}",
            "journal": "Journal of Clinical Immunology",
            "keywords": ["autoimmune disorders", "immunomodulators", "personalized medicine"],
            "article_url": "https://pubmed.ncbi.nlm.nih.gov/sample1/",
            "pmid": "sample1"
        },
        {
            "title": "Machine Learning Applications in Early Disease Detection",
            "abstract": "This study evaluates the efficacy of various machine learning algorithms in predicting disease onset from biomarker data. Using a dataset of 10,000 patients across multiple centers, we demonstrate significant improvements in early detection rates for several chronic conditions.",
            "authors": ["David A. Roberts", "Emma L. Thompson"],
            "publication_date": f"March {current_year}",
            "journal": "Digital Health Research",
            "keywords": ["machine learning", "disease prediction", "biomarkers"],
            "article_url": "https://pubmed.ncbi.nlm.nih.gov/sample2/",
            "pmid": "sample2"
        },
        {
            "title": "Comparative Effectiveness of Novel Anticoagulants in Preventing Stroke",
            "abstract": "This meta-analysis compares outcomes of direct oral anticoagulants versus traditional therapy in stroke prevention. Results indicate superior efficacy profiles for newer agents with reduced bleeding risks in specific patient populations.",
            "authors": ["Jennifer M. Lopez", "Robert K. Chen", "Thomas Wilson"],
            "publication_date": f"June {current_year-1}",
            "journal": "Stroke Prevention Research",
            "keywords": ["anticoagulants", "stroke prevention", "meta-analysis"],
            "article_url": "https://pubmed.ncbi.nlm.nih.gov/sample3/",
            "pmid": "sample3"
        },
        {
            "title": "Genetic Markers for Treatment Response in Major Depressive Disorder",
            "abstract": "This research identifies specific genetic polymorphisms associated with differential responses to antidepressant medications. The findings suggest potential for genotype-guided treatment selection to improve outcomes in depression management.",
            "authors": ["Natasha Singh", "Carlos Rodriguez"],
            "publication_date": f"October {current_year-1}",
            "journal": "Journal of Psychiatric Genetics",
            "keywords": ["depression", "pharmacogenomics", "personalized psychiatry"],
            "article_url": "https://pubmed.ncbi.nlm.nih.gov/sample4/",
            "pmid": "sample4"
        },
        {
            "title": "Microbiome Alterations Associated with Inflammatory Bowel Disease Progression",
            "abstract": "This longitudinal study tracks changes in gut microbiota composition during inflammatory bowel disease progression. We identify specific bacterial signatures that precede clinical flares and may serve as early warning biomarkers.",
            "authors": ["Ahmed Hassan", "Julia Chen", "Marcus Williams"],
            "publication_date": f"April {current_year-1}",
            "journal": "Gastroenterology Research",
            "keywords": ["microbiome", "inflammatory bowel disease", "biomarkers"],
            "article_url": "https://pubmed.ncbi.nlm.nih.gov/sample5/",
            "pmid": "sample5"
        }
    ]
    
    return mock_articles

# Functions for OpenAI interaction
def summarize_abstract(abstract, max_length=300):
    """Use OpenAI to create a concise summary of an abstract."""
    try:
        prompt = f"Summarize the following medical abstract in about 2-3 sentences (maximum {max_length} characters):\n\n{abstract}"

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a medical research summarizer. Create concise, accurate summaries that capture the key findings and implications."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Error generating summary: {e}")
        return "Summary generation failed. Please try again later."

def answer_question(question, articles_data):
    """Answer a question based on the articles data using OpenAI."""
    try:
        # Prepare context from articles
        context = ""
        for i, article in enumerate(articles_data, 1):
            context += f"Article {i}: {article['title']}\n"
            context += f"Abstract: {article['abstract']}\n"
            context += f"Authors: {', '.join(article['authors'])}\n"
            context += f"Publication: {article['journal']}, {article['publication_date']}\n\n"

        prompt = f"""Based on these medical research articles, please answer the following question:

Context articles:
{context}

Question: {question}

Answer the question factually based only on the information provided in these articles. If the articles don't contain relevant information to answer the question, clearly state that it cannot be answered from the provided context."""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a medical research assistant. Provide factual, accurate answers based only on the provided medical literature. Be clear about limitations when information is insufficient."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Error answering question: {e}")
        return "Question answering failed. Please try again later."

def extract_key_findings(articles_data):
    """Extract key findings from multiple articles using OpenAI."""
    try:
        # Prepare context from articles
        context = ""
        for i, article in enumerate(articles_data, 1):
            context += f"Article {i}: {article['title']}\n"
            context += f"Abstract: {article['abstract']}\n\n"

        prompt = f"""Analyze these medical research articles and identify the 3-5 most important findings or trends across them:

{context}

Format your response as bullet points, focusing on clinically relevant insights and consensus findings."""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a medical research analyst. Identify key findings and patterns across multiple research articles."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Error extracting key findings: {e}")
        return "Analysis failed. Please try again later."

def generate_research_gaps(articles_data):
    """Identify research gaps based on the articles using OpenAI."""
    try:
        # Prepare context from articles
        context = ""
        for i, article in enumerate(articles_data, 1):
            context += f"Article {i}: {article['title']}\n"
            context += f"Abstract: {article['abstract']}\n\n"

        prompt = f"""Based on these medical research articles, identify 2-4 important research gaps or unanswered questions:

{context}

Format your response as bullet points, focusing on clinically relevant gaps that future research should address."""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a medical research strategist. Identify important gaps in the current research landscape."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Error identifying research gaps: {e}")
        return "Analysis failed. Please try again later."

def generate_clinical_recommendations(articles_data):
    """Generate clinical practice recommendations based on the articles using OpenAI."""
    try:
        # Prepare context from articles
        context = ""
        for i, article in enumerate(articles_data, 1):
            context += f"Article {i}: {article['title']}\n"
            context += f"Abstract: {article['abstract']}\n\n"

        prompt = f"""Based on these medical research articles, suggest 3-4 evidence-based clinical recommendations:

{context}

Format your response as bullet points with brief explanations, focusing on practical applications for clinicians. Be clear about the strength of evidence."""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a medical research consultant. Provide evidence-based clinical recommendations based on research findings."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Error generating clinical recommendations: {e}")
        return "Analysis failed. Please try again later."

def generate_citation(article):
    """Generate citation in APA format."""
    authors = article['authors']
    if len(authors) == 1:
        author_text = authors[0]
    elif len(authors) == 2:
        author_text = f"{authors[0]} & {authors[1]}"
    elif len(authors) > 2:
        author_text = f"{authors[0]} et al."
    else:
        author_text = "Unknown"
    
    year_match = re.search(r'\b(19|20)\d{2}\b', article['publication_date'])
    year = year_match.group() if year_match else "n.d."
    
    return f"{author_text}. ({year}). {article['title']}. {article['journal']}. Retrieved from {article['article_url']}"

# Session state initialization
if 'articles' not in st.session_state:
    st.session_state.articles = []
if 'last_query' not in st.session_state:
    st.session_state.last_query = ""
if 'result_count' not in st.session_state:
    st.session_state.result_count = 0
if 'article_summaries' not in st.session_state:
    st.session_state.article_summaries = {}
if 'search_history' not in st.session_state:
    st.session_state.search_history = []
if 'key_findings' not in st.session_state:
    st.session_state.key_findings = ""
if 'research_gaps' not in st.session_state:
    st.session_state.research_gaps = ""
if 'clinical_recommendations' not in st.session_state:
    st.session_state.clinical_recommendations = ""
if 'user_question' not in st.session_state:
    st.session_state.user_question = ""

# App Header
st.markdown("<h1 class='main-header'>PubMedSearch-Summarizer</h1>", unsafe_allow_html=True)
st.markdown("<p class='sub-header'>Advanced PubMed Research Assistant</p>", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.image("logo.png", width=100)
    st.markdown("## Search Settings")
    
    with st.form(key='search_form'):
        # Main search parameters
        st.markdown("### Basic Search")
        keywords = st.text_input("Keywords (comma separated)", placeholder="e.g. treatment, therapy, intervention")
        disease = st.text_input("Disease/Condition", placeholder="e.g. diabetes, hypertension")
        
        # Advanced search options
        st.markdown("### Advanced Filters")
        logic_operator = st.selectbox("Search Logic", ["AND", "OR"])
        
        col1, col2 = st.columns(2)
        with col1:
            start_year = st.number_input("From Year", min_value=1900, max_value=datetime.now().year, value=datetime.now().year-5)
        with col2:
            end_year = st.number_input("To Year", min_value=1900, max_value=datetime.now().year, value=datetime.now().year)
        
        author = st.text_input("Author Name", placeholder="e.g. Smith AB")
        journal = st.text_input("Journal Name", placeholder="e.g. JAMA, Lancet")
        
        max_results = st.slider("Maximum Results", 1, 20, 5)
        
        search_button = st.form_submit_button("Search PubMed")
    
    # Search history section
    if st.session_state.search_history:
        st.markdown("### Recent Searches")
        for i, history_item in enumerate(st.session_state.search_history[-5:]):
            if st.button(f"{history_item[:40]}...", key=f"history_{i}"):
                st.session_state.last_query = history_item
                with st.spinner("Searching PubMed..."):
                    st.session_state.result_count = fetch_pubmed_count(history_item)
                    st.session_state.articles = fetch_pubmed_articles(history_item, max_results)
                    # Clear previous summaries
                    st.session_state.article_summaries = {}
                    st.session_state.key_findings = ""
                    st.session_state.research_gaps = ""
                    st.session_state.clinical_recommendations = ""
                st.rerun()
    
    st.markdown("---")
    st.markdown("### About")
    st.markdown("""
    **PubMedSearch-Summarizer** is an advanced PubMed research assistant that helps medical professionals and researchers quickly find, summarize, and analyze relevant medical literature.
    
    Powered by OpenAI and PubMed API.

    contact: nahiyan.cuet@gmail.com
    """)

# Handle search
if search_button:
    # Process keywords
    keyword_list = [k.strip() for k in keywords.split(',') if k.strip()]
    
    # Build query
    year_range = [start_year, end_year] if start_year and end_year else None
    query = build_pubmed_query(keyword_list, disease, year_range, author, journal, logic_operator)
    
    if query:
        st.session_state.last_query = query
        
        # Add to search history
        if query not in st.session_state.search_history:
            st.session_state.search_history.append(query)
        
        with st.spinner("Searching PubMed..."):
            st.session_state.result_count = fetch_pubmed_count(query)
            st.session_state.articles = fetch_pubmed_articles(query, max_results, use_mock_if_empty=True)
            # Clear previous summaries
            st.session_state.article_summaries = {}
            st.session_state.key_findings = ""
            st.session_state.research_gaps = ""
            st.session_state.clinical_recommendations = ""
    else:
        st.warning("Please enter at least keywords or a disease to search.")

# Main content area
if st.session_state.articles:
    # Results metrics bar
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""
        <div class="metrics-card">
            <div class="metrics-value">{st.session_state.result_count:,}</div>
            <div class="metrics-label">Total Articles</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        most_recent_year = max([int(re.findall(r'\d{4}', article['publication_date'])[-1]) 
                             if re.findall(r'\d{4}', article['publication_date']) else 0 
                             for article in st.session_state.articles], default=0)
        st.markdown(f"""
        <div class="metrics-card">
            <div class="metrics-value">{most_recent_year}</div>
            <div class="metrics-label">Most Recent Year</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        avg_authors = round(sum(len(article['authors']) for article in st.session_state.articles) / len(st.session_state.articles), 1)
        st.markdown(f"""
        <div class="metrics-card">
            <div class="metrics-value">{avg_authors}</div>
            <div class="metrics-label">Avg. Authors Per Study</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Articles", "Analysis", "Q&A", "Export"])
    
    # Tab 1: Articles
    with tab1:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        
        # Display the results
        for i, article in enumerate(st.session_state.articles):
            with st.expander(f"{i+1}. {article['title']}", expanded=True):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.markdown(f"**Journal:** {article['journal']}")
                    st.markdown(f"**Published:** {article['publication_date']}")
                    st.markdown(f"**Authors:** {', '.join(article['authors'])}")
                    
                    # Display abstract
                    st.markdown("#### Abstract")
                    st.markdown(article['abstract'])
                    
                    # Display or generate summary
                    st.markdown("#### Summary")
                    if article['pmid'] not in st.session_state.article_summaries:
                        with st.spinner("Generating summary..."):
                            summary = summarize_abstract(article['abstract'])
                            st.session_state.article_summaries[article['pmid']] = summary
                    
                    st.markdown(f"<div class='article-summary'>{st.session_state.article_summaries[article['pmid']]}</div>", unsafe_allow_html=True)
                    
                    # Display keywords if available
                    if article['keywords']:
                        st.markdown("#### Keywords")
                        st.markdown(", ".join([f"<span class='badge'>{kw}</span>" for kw in article['keywords']]), unsafe_allow_html=True)
                with col2:
                    st.markdown(f"[View on PubMed]({article['article_url']})")
                    st.markdown(f"PMID: {article['pmid']}")
                    
                    # Citation button
                    citation = generate_citation(article)
                    if st.button(f"Copy Citation", key=f"cite_{i}"):
                        st.code(citation)
                        st.success("Citation copied to clipboard!")
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Tab 2: Analysis
    with tab2:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        
        if not st.session_state.key_findings:
            if st.button("Generate Analysis"):
                with st.spinner("Analyzing articles..."):
                    # Generate key findings
                    st.session_state.key_findings = extract_key_findings(st.session_state.articles)
                    
                    # Generate research gaps
                    st.session_state.research_gaps = generate_research_gaps(st.session_state.articles)
                    
                    # Generate clinical recommendations
                    st.session_state.clinical_recommendations = generate_clinical_recommendations(st.session_state.articles)
        
        if st.session_state.key_findings:
            # Display the analysis results
            st.markdown("### Key Findings")
            st.markdown(st.session_state.key_findings)
            
            st.markdown("### Research Gaps")
            st.markdown(st.session_state.research_gaps)
            
            st.markdown("### Clinical Recommendations")
            st.markdown(st.session_state.clinical_recommendations)
        else:
            st.info("Click 'Generate Analysis' to extract key findings, research gaps, and clinical recommendations from the articles.")
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Tab 3: Q&A
    with tab3:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        
        st.markdown("### Ask a Question About These Articles")
        st.markdown("Enter a question about the research articles and get an AI-generated answer based on their content.")
        
        question = st.text_input("Your question:", key="qa_input")
        
        if st.button("Ask Question") and question:
            with st.spinner("Generating answer..."):
                st.session_state.user_question = question
                answer = answer_question(question, st.session_state.articles)
            
            st.markdown("### Answer")
            st.markdown(answer)
        
        if st.session_state.user_question and not question:
            st.info("Enter a new question above and click 'Ask Question'.")
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Tab 4: Export
    with tab4:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        
        st.markdown("### Export Results")
        
        # Create dataframe for export
        export_data = []
        for article in st.session_state.articles:
            export_data.append({
                "Title": article['title'],
                "Authors": ", ".join(article['authors']),
                "Journal": article['journal'],
                "Publication Date": article['publication_date'],
                "Abstract": article['abstract'],
                "Summary": st.session_state.article_summaries.get(article['pmid'], ""),
                "PMID": article['pmid'],
                "URL": article['article_url']
            })
        
        df = pd.DataFrame(export_data)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # CSV export
            csv = df.to_csv(index=False)
            st.download_button(
                label="Download as CSV",
                data=csv,
                file_name="pubmed_search_results.csv",
                mime="text/csv"
            )
        
        with col2:
            # JSON export
            json_str = df.to_json(orient="records")
            st.download_button(
                label="Download as JSON",
                data=json_str,
                file_name="pubmed_search_results.json",
                mime="application/json"
            )
        
        # Bibliography export
        st.markdown("### Export Bibliography")
        
        citations = []
        for article in st.session_state.articles:
            citations.append(generate_citation(article))
        
        citation_text = "\n\n".join(citations)
        st.download_button(
            label="Download Bibliography",
            data=citation_text,
            file_name="bibliography.txt",
            mime="text/plain"
        )
        
        st.markdown("</div>", unsafe_allow_html=True)

else:
    # Display sample searches when no search has been performed
    st.markdown("## Sample Searches")
    st.markdown("Click on any sample search below to get started:")
    
    sample_searches = [
        {"title": "Recent COVID-19 Treatments", "keywords": "covid-19, treatment, therapy", "disease": "COVID-19", "year_range": [2020, datetime.now().year]},
        {"title": "Diabetes Management Advances", "keywords": "management, therapy, intervention", "disease": "diabetes mellitus type 2", "year_range": [2018, datetime.now().year]},
        {"title": "Cancer Immunotherapy Research", "keywords": "immunotherapy, checkpoint inhibitors", "disease": "cancer", "year_range": [2019, datetime.now().year]},
        {"title": "Heart Failure Guidelines", "keywords": "guidelines, management, therapy", "disease": "heart failure", "year_range": [2017, datetime.now().year]}
    ]
    
    col1, col2 = st.columns(2)
    
    for i, sample in enumerate(sample_searches):
        col = col1 if i % 2 == 0 else col2
        with col:
            st.markdown(f"""
            <div class="sample-search" id="sample-{i}">
                <h4>{sample['title']}</h4>
                <p><strong>Keywords:</strong> {sample['keywords']}</p>
                <p><strong>Disease:</strong> {sample['disease']}</p>
                <p><strong>Years:</strong> {sample['year_range'][0]}-{sample['year_range'][1]}</p>
            </div>
            """, unsafe_allow_html=True)
            
            # Add functionality to the sample search
            if st.button(f"Run this search", key=f"sample_search_{i}"):
                keywords_list = [k.strip() for k in sample['keywords'].split(',')]
                query = build_pubmed_query(
                    keywords_list, 
                    sample['disease'], 
                    sample['year_range']
                )
                
                st.session_state.last_query = query
                
                with st.spinner("Searching PubMed..."):
                    st.session_state.result_count = fetch_pubmed_count(query)
                    st.session_state.articles = fetch_pubmed_articles(query, 5, use_mock_if_empty=True)
                    st.session_state.article_summaries = {}
                    st.session_state.key_findings = ""
                    st.session_state.research_gaps = ""
                    st.session_state.clinical_recommendations = ""
                
                # Add to search history
                if query not in st.session_state.search_history:
                    st.session_state.search_history.append(query)
                
                st.rerun()
    
    # Display app instructions
    st.markdown("## How to Use This App")
    st.markdown("""
    1. **Basic Search**: Enter keywords and/or disease names in the sidebar
    2. **Advanced Filters**: Refine your search with publication years, author names, and journal names
    3. **Review Results**: Browse through articles, read abstracts and AI-generated summaries
    4. **Analyze**: Generate key findings, research gaps, and clinical recommendations
    5. **Ask Questions**: Use the Q&A tab to ask specific questions about the articles
    6. **Export**: Download your results in various formats
    """)

# Footer
st.markdown("""
<div class="footer">
    <p>PubMedSearch-Summarizer © 2024 | Developed by Nahiyan</p>
    <p>Uses PubMed API for article retrieval and OpenAI API for text analysis</p>
</div>
""", unsafe_allow_html=True)
