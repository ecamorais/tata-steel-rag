from src.retriever import hybrid_search

queries = {
    'turnover TSG amalgamation': 74,
    'Chairman N Chandrasekaran': 14,
    'India GDP growth FY2021-22': 14,
    'Tata Steel manufacturing locations': None,
    'Tata Steel vision': None,
    'Tata Steel employees FY2021-22': None,
    'Tata Steel total revenue FY2021-22': None,
    'Dow Jones Sustainability Index': None,
}

for q, expected_page in queries.items():
    hits = hybrid_search(q, top_k=10)
    fy2022_hits = [h['page_number'] for h in hits if h['source_file'] == 'tata-steel-fy2022.pdf']
    hit_expected = expected_page in fy2022_hits if expected_page else None
    print(f'{q!r}: fy2022 pages in top10 = {fy2022_hits} | expected_page={expected_page} found={hit_expected}')