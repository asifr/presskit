---
title: "About {{ site.author }}"
category: "personal"
---

# About {{ site.author }}

This site was built on {{ build.date }} and is currently version {{ site.version }}.

{% if category == "personal" %}
This is a personal page about {{ site.author }}.
{% endif %}
