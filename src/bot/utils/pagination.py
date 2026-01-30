"""Утилиты для пагинации"""


def paginate_items(items: list, page: int = 0, per_page: int = 10) -> tuple:
    """Разбить список на страницы"""
    start = page * per_page
    end = start + per_page
    return items[start:end], len(items), (len(items) + per_page - 1) // per_page


def filter_items_by_search(items: list, search_query: str) -> list:
    """Отфильтровать список по поисковому запросу"""
    if not search_query:
        return items
    
    search_lower = search_query.lower()
    return [item for item in items if search_lower in item.lower()]


def group_by_alphabet(items: list) -> dict:
    """Группировать элементы по первой букве алфавита"""
    groups = {}
    for item in items:
        first_char = item[0].upper() if item else '0'
        if not first_char.isalpha():
            first_char = '0-9'
        if first_char not in groups:
            groups[first_char] = []
        groups[first_char].append(item)
    
    # Сортируем группы и элементы внутри групп
    for key in groups:
        groups[key].sort()
    
    return dict(sorted(groups.items()))


