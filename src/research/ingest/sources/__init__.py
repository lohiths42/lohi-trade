"""Filings_Source adapters (design §3.2).

One module per external source: BSE public announcement feed, NSE public
announcement feed, user-upload watch folder, and the optional SEBI EDIFAR
and company investor-relations PDF sources. Each source publishes index
events onto the `research:index_events` Redis stream.
"""
