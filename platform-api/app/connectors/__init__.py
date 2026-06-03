"""Connector framework for Tablescope data sources.

Databases (PostgreSQL/MySQL/SQL Server/Oracle) are reached live through Teiid via
JDBC.  SaaS apps (HubSpot, Salesforce) are REST APIs, so they are modelled as
*connectors* that sync a selected object into a local Postgres staging table,
which is then exposed to Teiid through the same database-table pipeline.

This package holds the SaaS connector interface and concrete implementations.
"""
