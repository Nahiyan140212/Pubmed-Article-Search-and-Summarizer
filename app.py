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
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

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

def generate_pdf_from_text(text):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=inch, leftMargin=inch, topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()
    story = []

    # Split text into paragraphs
    paragraphs = text.split('\n\n')
    for para in paragraphs:
        # Clean and format paragraph
        para = para.strip().replace('\n', ' ')
        if para.startswith('# '):
            story.append(Paragraph(para[2:], styles['Heading1']))
        elif para.startswith('## '):
            story.append(Paragraph(para[3:], styles['Heading2']))
        elif para.startswith('### '):
            story.append(Paragraph(para[4:], styles['Heading3']))
        else:
            story.append(Paragraph(para, styles['BodyText']))
        story.append(Spacer(1, 0.2 * inch))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# Functions for PubMed API interaction
def build_pubmed_query(keywords, disease=None, year_range=None, author=None, journal=None, logic_operator="AND"):
    """Build a query string for PubMed using various filters."""
    keywords_str = " ".join(f'"{kw}"' for kw in keywords if kw.strip())
    query_parts = []
    
    if keywords_str:
        query_parts.append(f"({keywords_str})")
    
    if disease and disease.strip():
        query_parts.append(f'("{disease}"[MeSH Terms] OR "{disease}"[All Fields])')
    
    if year_range and len(year_range) == 2:
        start_year, end_year = year_range
        query_parts.append(f"({start_year}[PDAT]:{end_year}[PDAT])")
    
    if author and author.strip():
        query_parts.append(f'"{author}"[Author]')
    
    if journal and journal.strip():
        query_parts.append(f'"{journal}"[Journal]')
    
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

def fetch_pubmed_articles(query, max_results=5, use_mock_if_empty=False):
    """Fetch articles from PubMed based on the query and return detailed information."""
    headers = {"User-Agent": "Mozilla/5.0"}
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
                date_tag = article.find("pubdate")
                author_tags = article.find_all("author")
                journal_tag = article.find("journal")
                keywords_tag = article.find_all("keyword")

                title = title_tag.get_text(strip=True) if title_tag else "No title"
                abstract = abstract_tag.get_text(separator=" ", strip=True) if abstract_tag else "No abstract available"
                
                authors = []
                for author in author_tags:
                    last = author.find("lastname")
                    fore = author.find("forename")
                    if last and fore:
                        authors.append(f"{fore.get_text()} {last.get_text()}")
                    elif last:
                        authors.append(last.get_text())
                authors = authors if authors else ["No authors listed"]

                journal_name = "Unknown Journal"
                if journal_tag:
                    journal_title = journal_tag.find("title")
                    if journal_title:
                        journal_name = journal_title.get_text(strip=True)

                keywords = [kw.get_text(strip=True) for kw in keywords_tag] if keywords_tag else []

                pub_date = "No date"
                if date_tag:
                    year = date_tag.find("year")
                    month = date_tag.find("month")
                    day = date_tag.find("day")
                    if year and month and day:
                        pub_date = f"{month.get_text()} {day.get_text()}, {year.get_text()}"
                    elif year and month:
                        pub_date = f"{month.get_text()} {year.get_text()}"
                    elif year:
                        pub_date = year.get_text()

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
        st.markdown("### Basic System: Search")
        keywords = st.text_input("Keywords (comma separated)", placeholder="e.g. treatment, therapy, intervention")
        disease = st.text_input("Disease/Condition", placeholder="e.g. diabetes, hypertension")
        
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
    
    if st.session_state.search_history:
        st.markdown("### Recent Searches")
        for i, history_item in enumerate(st.session_state.search_history[-5:]):
            if st.button(f"{history_item[:40]}...", key=f"history_{i}"):
                st.session_state.last_query = history_item
                with st.spinner("Searching PubMed..."):
                    st.session_state.result_count = fetch_pubmed_count(history_item)
                    st.session_state.articles = fetch_publications(history_item, max_results)
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
    keyword_list = [k.strip() for k in keywords.split(',') if k.strip()]
    year_range = [start_year, end_year] if start_year and end_year else None
    query = build_pubmed_query(keyword_list, disease, year_range, author, journal, logic_operator)
    
    if query:
        st.session_state.last_query = query
        if query not in st.session_state.search_history:
            st.session_state.search_history.append(query)
        
        with st.spinner("Searching PubMed..."):
            st.session_state.result_count = fetch_pubmed_count(query)
            st.session_state.articles = fetch_pubmed_articles(query, max_results)
            st.session_state.article_summaries = {}
            st.session_state.key_findings = ""
            st.session_state.research_gaps = ""
            st.session_state.clinical_recommendations = ""
    else:
        st.warning("Please enter at least keywords or a disease to search.")

# Main content area
if st.session_state.articles:
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
    
    tab1, tab2, tab3, tab4 = st.tabs(["Articles", "Analysis", "Q&A", "Export"])
    
    with tab1:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        for i, article in enumerate(st.session_state.articles):
            with st.expander(f"{i+1}. {article['title']}", expanded=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Journal:** {article['journal']}")
                    st.markdown(f"**Published:** {article['publication_date']}")
                    st.markdown(f"**Authors:** {', '.join(article['authors'])}")
                    st.markdown("### Abstract")
                    st.markdown(article['abstract'])
                    if article['pmid'] not in st.session_state.article_summaries:
                        with st.spinner("Generating summary..."):
                            summary = summarize_abstract(article['abstract'])
                            st.session_state.article_summaries[article['pmid']] = summary
                    st.markdown("### Summary")
                    st.markdown(f"<div class='article-summary'>{st.session_state.article_summaries[article['pmid']]}</div>", unsafe_allow_html=True)
                with col2:
                    st.markdown("### Quick Links")
                    st.markdown(f"[View on PubMed]({article['article_url']})")
                    if article['keywords']:
                        st.markdown("### Keywords")
                        for kw in article['keywords']:
                            st.markdown(f"<span class='badge'>{kw}</span>", unsafe_allow_html=True)
                    st.markdown("### Citation")
                    st.code(generate_citation(article), language=None)
        st.markdown("</div>", unsafe_allow_html=True)
    
    with tab2:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        if not st.session_state.key_findings:
            with st.spinner("Analyzing articles..."):
                st.session_state.key_findings = extract_key_findings(st.session_state.articles)
        if not st.session_state.research_gaps:
            with st.spinner("Identifying research gaps..."):
                st.session_state.research_gaps = generate_research_gaps(st.session_state.articles)
        if not st.session_state.clinical_recommendations:
            with st.spinner("Generating clinical recommendations..."):
                st.session_state.clinical_recommendations = generate_clinical_recommendations(st.session_state.articles)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### Key Findings Across Articles")
            st.markdown(st.session_state.key_findings)
            st.markdown("### Research Gaps & Future Directions")
            st.markdown(st.session_state.research_gaps)
        with col2:
            st.markdown("### Clinical Recommendations")
            st.markdown(st.session_state.clinical_recommendations)
            st.markdown("### Publication Timeline")
            years_data = []
            for article in st.session_state.articles:
                year_match = re.search(r'\b(19|20)\d{2}\b', article['publication_date'])
                if year_match:
                    years_data.append(int(year_match.group()))
            if years_data:
                years_df = pd.DataFrame(years_data, columns=['Year'])
                year_counts = years_df['Year'].value_counts().sort_index()
                year_counts_df = pd.DataFrame({
                    'Year': year_counts.index,
                    'Count': year_counts.values
                })
                st.bar_chart(year_counts_df.set_index('Year'))
            else:
                st.info("Unable to extract publication years for timeline.")
        st.markdown("</div>", unsafe_allow_html=True)

    with tab3:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        st.markdown("### Ask Questions About These Articles")
        st.markdown("Ask any question related to the findings, methods, or implications of these articles.")
        user_question = st.text_input("Your question:", key="question_input")
        if user_question and user_question != st.session_state.user_question:
            st.session_state.user_question = user_question
            with st.spinner("Analyzing question..."):
                answer = answer_question(user_question, st.session_state.articles)
                st.markdown(f"<div class='qa-box'><strong>Q: {user_question}</strong><br><br>{answer}</div>", unsafe_allow_html=True)
        elif st.session_state.user_question:
            answer = answer_question(st.session_state.user_question, st.session_state.articles)
            st.markdown(f"<div class='qa-box'><strong>Q: {st.session_state.user_question}</strong><br><br>{answer}</div>", unsafe_allow_html=True)
        
        st.markdown("### Sample Questions")
        sample_questions = [
            "What are the main treatment approaches discussed in these articles?",
            "What methodologies were used across these studies?",
            "What are the limitations of the research presented?",
            "How do these findings impact clinical practice?",
            "What patient populations were included in these studies?"
        ]
        for sample in sample_questions:
            if st.button(sample, key=f"sample_{hash(sample)}"):
                st.session_state.user_question = sample
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    
    with tab4:
        st.markdown("<div class='tab-content'>", unsafe_allow_html=True)
        st.markdown("### Export Options")
        export_type = st.radio(
            "Select export format:",
            ["Summary Report", "Detailed Report", "BibTeX Citations", "CSV Data"]
        )
        if export_type == "Summary Report":
            report = f"""# Literature Review Summary
Generated on {datetime.now().strftime('%B %d, %Y')}

## Overview
Found {st.session_state.result_count:,} results for query: {st.session_state.last_query.replace('"', '\\"')}

## Key Findings
{st.session_state.key_findings}

## Research Gaps
{st.session_state.research_gaps}

## Clinical Recommendations
{st.session_state.clinical_recommendations}

## Articles Reviewed
"""
            for i, article in enumerate(st.session_state.articles, 1):
                report += f"""
### {i}. {article['title']}
**Authors:** {', '.join(article['authors'])}
**Journal:** {article['journal']}, {article['publication_date']}
**Link:** {article['article_url']}

**Summary:** {st.session_state.article_summaries.get(article['pmid'], 'No summary available')}

"""
            pdf_summary = generate_pdf_from_text(report)
            st.download_button(
                label="Download Summary Report",
                data=pdf_summary,
                file_name=f"medsearch_summary_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf"
            )
        
        elif export_type == "Detailed Report":
            detailed_report = f"""# Comprehensive Literature Review
Generated on {datetime.now().strftime('%B %d, %Y')}

## Search Details
* Query: {st.session_state.last_query.replace('"', '\\"')}
* Total Results: {st.session_state.result_count}
* Articles Analyzed: {len(st.session_state.articles)}

## Synthesis
### Key Findings
{st.session_state.key_findings}

### Research Gaps
{st.session_state.research_gaps}

### Clinical Recommendations
{st.session_state.clinical_recommendations}

## Detailed Article Summaries
"""
            for i, article in enumerate(st.session_state.articles, 1):
                detailed_report += f"""
### {i}. {article['title']}
**Authors:** {', '.join(article['authors'])}
**Journal:** {article['journal']}, {article['publication_date']}
**PMID:** {article['pmid']}
**Link:** {article['article_url']}

**Keywords:** {', '.join(article['keywords']) if article['keywords'] else 'None listed'}

**Abstract:**
{article['abstract']}

**Summary:**
{st.session_state.article_summaries.get(article['pmid'], 'No summary available')}

**Citation:**
{generate_citation(article)}

---
"""
            pdf_detailed = generate_pdf_from_text(detailed_report)
            st.download_button(
                label="Download Detailed Report",
                data=pdf_detailed,
                file_name=f"medsearch_detailed_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf"
            )
        
        elif export_type == "BibTeX Citations":
            bibtex = ""
            for article in st.session_state.articles:
                year_match = re.search(r'\b(19|20)\d{2}\b', article['publication_date'])
                year = year_match.group() if year_match else "n.d."
                first_author_last = article['authors'][0].split()[-1] if article['authors'] else "Unknown"
                citation_key = f"{first_author_last.lower()}{year}"
                bibtex += f"""@article{{{citation_key},
  title = {{{article['title']}}},
  author = {{{' and '.join(article['authors'])}}},
  journal = {{{article['journal']}}},
  year = {{{year}}},
  url = {{{article['article_url']}}},
  pmid = {{{article['pmid']}}}
}}

"""
            st.download_button(
                label="Download BibTeX Citations",
                data=bibtex,
                file_name=f"medsearch_citations_{datetime.now().strftime('%Y%m%d')}.bib",
                mime="application/x-bibtex"
            )
        
        elif export_type == "CSV Data":
            csv_data = []
            for article in st.session_state.articles:
                csv_data.append({
                    "Title": article['title'],
                    "Authors": '; '.join(article['authors']),
                    "Journal": article['journal'],
                    "Publication Date": article['publication_date'],
                    "Abstract": article['abstract'],
                    "Keywords": '; '.join(article['keywords']) if article['keywords'] else '',
                    "URL": article['article_url'],
                    "PMID": article['pmid'],
                    "Summary": st.session_state.article_summaries.get(article['pmid'], 'No summary available')
                })
            df = pd.DataFrame(csv_data)
            csv = df.to_csv(index=False)
            st.download_button(
                label="Download CSV Data",
                data=csv,
                file_name=f"medsearch_data_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        st.markdown("</div>", unsafe_allow_html=True)

else:
    st.markdown("## Welcome to PubMedSearch")
    st.markdown("""
    Use the search form in the sidebar to find and analyze medical research articles.
    
    Not sure where to start? Try one of these sample searches:
    """)
    
    sample_searches = [
        {"title": "Recent advances in COVID-19 treatments", "keywords": "COVID-19, treatment, telehealth", "disease": "COVID-19"},
        {"title": "Buprenorphine usage for Opioid Use Disorder", "keywords": "telehealth, telemedicine, remote", "disease": "Opioid Use Disorder"},
        {"title": "Cancer immunotherapy outcomes", "keywords": "immunotherapy, outcomes, survival", "disease": "cancer"},
        {"title": "Hypertension control strategies", "keywords": "control, strategy, intervention", "disease": "hypertension"},
        {"title": "Mental health telehealth services", "keywords": "telehealth, telemedicine, remote", "disease": "Mental Health"}
    ]
    
    col1, col2 = st.columns(2)
    for i, sample in enumerate(sample_searches):
        col = col1 if i % 2 == 0 else col2
        with col:
            st.markdown(f"<div class='sample-search' id='sample_{i}'>", unsafe_allow_html=True)
            st.markdown(f"#### {sample['title']}")
            st.markdown(f"Keywords: {sample['keywords']}")
            st.markdown(f"Disease: {sample['disease']}")
            if st.button("Try This Search", key=f"sample_btn_{i}"):
                keyword_list = [k.strip() for k in sample['keywords'].split(',') if k.strip()]
                query = build_pubmed_query(keyword_list, sample['disease'])
                st.session_state.last_query = query
                if query not in st.session_state.search_history:
                    st.session_state.search_history.append(query)
                with st.spinner("Searching PubMed..."):
                    st.session_state.result_count = fetch_pubmed_count(query)
                    st.session_state.articles = fetch_pubmed_articles(query, 5)
                    st.session_state.article_summaries = {}
                    st.session_state.key_findings = ""
                    st.session_state.research_gaps = ""
                    st.session_state.clinical_recommendations = ""
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown("""
    ### Features
    - **Advanced PubMed Search**: Search by keywords, disease, author, journal, and date range
    - **Summaries**: Get concise summaries of each article
    - **Cross-Article Analysis**: Identify key findings, research gaps, and clinical recommendations
    - **Interactive Q&A**: Ask questions about the articles and get informed answers
    - **Export Options**: Generate reports or export citations in various formats
    """)

# Footer
st.markdown("""
<div class="footer">
    Developed for Medical Researchers •
    <br>© 2025 Nahiyan Noor
</div>
""", unsafe_allow_html=True)
