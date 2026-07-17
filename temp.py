import requests
import feedparser

# 1. Grab the raw XML
response = requests.get("https://news.ycombinator.com/rss")

# 2. Parse it
parsed_data = feedparser.parse(response.content)

# 3. Print the first article title to prove it works
print(parsed_data.entries[0].title)
print(parsed_data.entries[0].link)

