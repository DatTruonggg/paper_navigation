import re
import os
import psycopg2
from dotenv import load_dotenv
from typing import Dict, Optional
load_dotenv()

DB_URL = os.getenv("POSTGRE_URL")


def detect_id_type(paper_id: str) -> str:
    """Detect paper ID type."""
    if not paper_id:
        return 'unknown'

    paper_id = paper_id.strip()

    # OpenAlex
    if re.match(r'^W\d{1,9}$', paper_id) or paper_id.startswith('https://openalex.org/W'):
        return 'openalex'

    # ArXiv
    if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', paper_id) or paper_id.startswith('https://arxiv.org/abs/'):
        return 'arxiv'

    # Semantic Scholar
    if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', paper_id):
        return 'semantic_scholar'

    return 'unknown'


def normalize_id(paper_id: str, id_type: str) -> str:
    """Normalize ID to standard format."""
    paper_id = paper_id.strip()

    if id_type == 'openalex' and paper_id.startswith('https://'):
        return paper_id.split('/')[-1]

    if id_type == 'arxiv' and paper_id.startswith('https://arxiv.org/abs/') or paper_id.startswith('http://arxiv.org/pdf/'):
        return paper_id.split('/')[-1]

    return paper_id


def map_to_openalex_id(paper_id: str) -> Optional[str]:
    """Map any paper ID to OpenAlex ID using PostgreSQL."""
    if not paper_id:
        return None

    id_type = detect_id_type(paper_id)
    normalized_id = normalize_id(paper_id, id_type)

    db_url = DB_URL.replace('postgresql+psycopg2://', 'postgresql://')

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cursor:
                if id_type == 'openalex':
                    cursor.execute("SELECT oa_paper_id FROM base_metadata WHERE oa_paper_id = %s", (normalized_id,))
                elif id_type == 'arxiv':
                    cursor.execute("SELECT oa_paper_id FROM base_metadata WHERE arxiv_id = %s", (normalized_id,))
                elif id_type == 'semantic_scholar':
                    cursor.execute("SELECT oa_paper_id FROM base_metadata WHERE s2_paper_id = %s", (normalized_id,))
                else:
                    # Title search fallback
                    cursor.execute("SELECT oa_paper_id FROM base_metadata WHERE title ILIKE %s LIMIT 1", (f"%{paper_id}%",))

                result = cursor.fetchone()
                if result:
                    return result[0]

                # Exact title fallback
                cursor.execute("SELECT oa_paper_id FROM base_metadata WHERE title = %s", (paper_id,))
                result = cursor.fetchone()
                if result:
                    return result[0]

    except Exception as e:
        print(f"Database error: {e}")

    return None

def get_paper_mappings(paper_id: str) -> Dict:
    """Get all available ID mappings for a paper."""
    openalex_id = map_to_openalex_id(paper_id)
    if not openalex_id:
        return {}

    db_url = DB_URL.replace('postgresql+psycopg2://', 'postgresql://')

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT oa_paper_id, arxiv_id, s2_paper_id, title
                    FROM base_metadata WHERE oa_paper_id = %s
                """, (openalex_id,))

                result = cursor.fetchone()
                if result:
                    columns = ['oa_paper_id', 'arxiv_id', 's2_paper_id', 'title']
                    return dict(zip(columns, result))

    except Exception as e:
        print(f"Database error: {e}")

    return {}

if __name__ == "__main__":
    id = str('df2b0e26d0599ce3e70df8a9da02e51594e0e992')
    print(get_paper_mappings(id))