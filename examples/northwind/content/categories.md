---
title: Categories
layout: page
---

## All Products by category

<table>
	<tr>
		<th>ID</th>
		<th>Name</th>
		<th>Description</th>
		<th>Products</th>
	</tr>
	{% for k in data.queries.categories %}
	<tr>
		<td>{{k.CategoryID}}</td>
		<td><a href="/categories/{{k.CategoryID}}.html">{{k.CategoryName}}</td>
		<td>{{k.Description}}</td>
		<td>
            <ul>
			{% for p in k.products -%}
				<li>
                    <a href="/products/{{p.ProductID}}.html">{{p.ProductName}}</a>
                </li>
			{% endfor %}
            </li>
		</td>
	</tr>
	{% endfor %}
</table>