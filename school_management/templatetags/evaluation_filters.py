from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """辞書からキーで値を取得するフィルタ"""
    return dictionary.get(key, '')
