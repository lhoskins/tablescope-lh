import React, { useEffect, useState, useCallback } from 'react';
import PropTypes from 'prop-types';

import AddBoxOutlinedIcon from '@material-ui/icons/AddBoxOutlined';
import DeleteIcon from '@material-ui/icons/Delete';
import MoreVertIcon from '@material-ui/icons/MoreVert';
import ArchiveIcon from '@material-ui/icons/Archive';
import UnarchiveIcon from '@material-ui/icons/Unarchive';
import VisibilityOffIcon from '@material-ui/icons/VisibilityOff';
import { IconButton, Menu, MenuItem, Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography } from '@material-ui/core';

import CreateDashboardDialog from '@/components/dashboards/CreateDashboardDialog';
import DataSourceViewer from './DataSourceViewer';
import DeleteDataSourceDialog from './DeleteDataSourceDialog';
import ProjectFileUpload from './ProjectFileUpload';
import ProjectSettingsMenu from '@/components/projects/ProjectSettingsMenu';

/* Helper: derive org slug from URL → /<org>/something */
const getOrgSlug = () => window.location.pathname.split('/')[1] || 'default';

/* Small helpers */
const formatDate = d => (d ? String(d).split('T')[0] : 'N/A');
const slugify = (str = '') =>
  String(str).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

export default function ProjectDetailPage({ projectId, onQuerySelected, onDashboardSelected }) {
  const [projectData, setProjectData] = useState(null);
  const [error, setError] = useState(null);
  const [selectedDataSource, setSelectedDataSource] = useState(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [dataSourceToDelete, setDataSourceToDelete] = useState(null);
  const [queryMenuAnchor, setQueryMenuAnchor] = useState(null);
  const [selectedQuery, setSelectedQuery] = useState(null);
  const [archiveDialogOpen, setArchiveDialogOpen] = useState(false);
  const [queryToArchive, setQueryToArchive] = useState(null);
  const [queryArchiveStatus, setQueryArchiveStatus] = useState({});
  const [dataSourceMenuAnchor, setDataSourceMenuAnchor] = useState(null);
  const [selectedDataSourceForMenu, setSelectedDataSourceForMenu] = useState(null);

  /* ───────────────── fetch project (dashboards + queries) ───────────────── */
  const fetchProjectData = useCallback(() => {
    if (!projectId) return;
    console.log(`[ProjectDetailPage] Fetching data for project ${projectId}...`);
    fetch(`/${getOrgSlug()}/api/projects/${projectId}/items`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        console.log(`[ProjectDetailPage] Received data for project ${projectId}:`, {
          project: data.project?.name,
          dashboardCount: data.dashboards?.length || 0,
          queryCount: data.queries?.length || 0,
          queryIds: data.queries?.map(q => q.id) || [],
          dataSourceCount: data.data_sources?.length || 0,
        });
        
        /* cache projectId globally so other components (e.g. CreateScope) can fetch queries list */
        window.__currentProjectId = data.project?.id || projectId;
        setProjectData(data);
        
        // Fetch archive status for each query
        if (data.queries && data.queries.length > 0) {
          const statusPromises = data.queries.map(q =>
            fetch(`/${getOrgSlug()}/api/queries/${q.id}`)
              .then(r => r.ok ? r.json() : null)
              .then(queryData => ({ id: q.id, is_archived: queryData?.is_archived || false }))
              .catch(() => ({ id: q.id, is_archived: false }))
          );
          
          Promise.all(statusPromises).then(statuses => {
            const statusMap = {};
            statuses.forEach(s => {
              statusMap[s.id] = s.is_archived;
            });
            console.log(`[ProjectDetailPage] Archive status for project ${projectId}:`, statusMap);
            setQueryArchiveStatus(statusMap);
          });
        }
      })
      .catch(err => {
        console.error(`[ProjectDetailPage] Error fetching project ${projectId}:`, err);
        setError(String(err));
      });
  }, [projectId]);

  useEffect(fetchProjectData, [fetchProjectData]);

  /* ───────────────── listen for project updates ───────────────── */
  useEffect(() => {
    const handleProjectUpdate = () => {
      console.log('[ProjectDetailPage] Project updated, refreshing data...');
      fetchProjectData();
    };

    const handleQuerySaved = () => {
      console.log('[ProjectDetailPage] Query saved, refreshing data...');
      fetchProjectData();
    };

    const handleDataSourceAdded = () => {
      console.log('[ProjectDetailPage] Data source added, refreshing data...');
      fetchProjectData();
    };

    // Listen for various project update events
    document.addEventListener('project-updated', handleProjectUpdate);
    document.addEventListener('new-query-saved', handleQuerySaved);
    document.addEventListener('query-saved', handleQuerySaved);
    document.addEventListener('data-source-added', handleDataSourceAdded);
    document.addEventListener('project-queries-updated', handleProjectUpdate);
    document.addEventListener('project-data-sources-updated', handleDataSourceAdded);

    return () => {
      document.removeEventListener('project-updated', handleProjectUpdate);
      document.removeEventListener('new-query-saved', handleQuerySaved);
      document.removeEventListener('query-saved', handleQuerySaved);
      document.removeEventListener('data-source-added', handleDataSourceAdded);
      document.removeEventListener('project-queries-updated', handleProjectUpdate);
      document.removeEventListener('project-data-sources-updated', handleDataSourceAdded);
    };
  }, [fetchProjectData]);

  /* ───────────────── poll for updates when page is visible ───────────────── */
  useEffect(() => {
    let intervalId;
    
    const startPolling = () => {
      // Poll every 5 seconds when page is visible
      intervalId = setInterval(() => {
        if (document.visibilityState === 'visible') {
          fetchProjectData();
        }
      }, 5000);
    };

    const stopPolling = () => {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    };

    // Start polling when page becomes visible
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchProjectData(); // Immediate refresh
        startPolling();
      } else {
        stopPolling();
      }
    };

    // Start polling if page is currently visible
    if (document.visibilityState === 'visible') {
      startPolling();
    }

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchProjectData]);

  /* ───────────────── early error / loading ───────────────── */
  if (error) return <div className="project-detail-page__error">Error: {error}</div>;
  if (!projectData) return <div className="project-detail-page__loading">Loading project #{projectId}…</div>;

  const { project, dashboards = [], queries = [], data_sources = [] } = projectData;

  /* ───────────────── handlers ───────────────── */
  const handleQueryClick = (q) => {
    /* 1. update globals so CreateScope sees newest values */
    window.__queryId             = q.id;
    window.__currentQueryId      = q.id;
    window.__queryName           = q.name;
    window.__currentSourceTable  = q.name;

    /* 2. optional callback to parent */
    if (onQuerySelected) {
      onQuerySelected(q.id, q.name);
    } else {
      /* fallback navigation to tsqueries page */
      window.location.href = `/${getOrgSlug()}/tsqueries/${q.id}`;
    }

    /* 3. fire event so DataGrid & other listeners react */
    document.dispatchEvent(
      new CustomEvent('query-selected', {
        detail: { queryId: q.id, queryName: q.name },
      }),
    );
  };

  const handleDashboardClick = (d) => {
    const slug = d.slug || slugify(d.name);
    if (onDashboardSelected) {
      onDashboardSelected(slug);
    } else {
      window.location.href = `/${getOrgSlug()}/dashboard/${slug}`;
    }
  };

  const handleDeleteDashboard = async (dashboard, event) => {
    // Prevent the card click event from firing
    event.stopPropagation();
    
    const confirmDelete = window.confirm(`Are you sure you want to permanently delete the dashboard "${dashboard.name}"? This action cannot be undone.`);
    
    if (!confirmDelete) return;
    
    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/dashboards/${dashboard.id}/delete`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to delete dashboard: ${response.status}`);
      }
      
      // Refresh the project data to remove the deleted dashboard
      fetchProjectData();
      
      // Optional: Show success message
      console.log(`Dashboard "${dashboard.name}" deleted successfully`);
      
    } catch (error) {
      console.error('Error deleting dashboard:', error);
      alert(`Failed to delete dashboard: ${error.message}`);
    }
  };

  const handleDeleteQuery = async (query, event) => {
    // Prevent the card click event from firing
    event.stopPropagation();
    
    const confirmDelete = window.confirm(`Are you sure you want to permanently delete the query "${query.name}"? This action cannot be undone and will also delete all associated visualizations, alerts, and widgets.`);
    
    if (!confirmDelete) return;
    
    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/queries/${query.id}/delete`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to delete query: ${response.status}`);
      }
      
      // Refresh the project data to remove the deleted query
      fetchProjectData();
      
      // Optional: Show success message
      console.log(`Query "${query.name}" deleted successfully`);
      
    } catch (error) {
      console.error('Error deleting query:', error);
      alert(`Failed to delete query: ${error.message}`);
    }
  };

  const handleRemoveQuery = async (query, event) => {
    // Prevent the card click event from firing
    event.stopPropagation();
    
    try {
      const orgSlug = getOrgSlug();
      
      // Get current query IDs and remove the one we want to delete
      const updatedQueryIds = queries
        .filter(q => q.id !== query.id)
        .map(q => q.id);
      
      const response = await fetch(`/${orgSlug}/api/projects/${projectId}/available_queries`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query_ids: updatedQueryIds }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to remove query: ${response.status}`);
      }
      
      // Refresh the project data
      fetchProjectData();
      console.log(`Query "${query.name}" removed from project successfully`);
      
    } catch (error) {
      console.error('Error removing query from project:', error);
      alert(`Failed to remove query from project: ${error.message}`);
    }
  };

  const handleRemoveDataSource = async (dataSource, event) => {
    // Prevent the card click event from firing
    event.stopPropagation();
    
    const dsName = dataSource.name || dataSource.data_source?.name;
    
    try {
      const orgSlug = getOrgSlug();
      const dsId = dataSource.data_source_id || dataSource.id;
      
      // Get current data source IDs and remove the one we want to delete
      const updatedDataSourceIds = data_sources
        .filter(ds => (ds.data_source_id || ds.id) !== dsId)
        .map(ds => ds.data_source_id || ds.id);
      
      const response = await fetch(`/${orgSlug}/api/projects/${projectId}/data_sources`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ data_source_ids: updatedDataSourceIds }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to remove data source: ${response.status}`);
      }
      
      // Refresh the project data
      fetchProjectData();
      console.log(`Data source "${dsName}" removed from project successfully`);
      
    } catch (error) {
      console.error('Error removing data source from project:', error);
      alert(`Failed to remove data source from project: ${error.message}`);
    }
  };

  const handleDeleteDataSource = (dataSource, event) => {
    // Prevent the card click event from firing
    event.stopPropagation();
    
    // Open the dialog instead of using window.confirm
    setDataSourceToDelete(dataSource);
    setDeleteDialogOpen(true);
  };

  const confirmDeleteDataSource = async (dataSource) => {
    try {
      const orgSlug = getOrgSlug();
      const dsId = dataSource.data_source_id || dataSource.id;
      const response = await fetch(`/${orgSlug}/api/data_sources/${dsId}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to delete data source: ${response.status}`);
      }
      
      // Refresh the project data
      fetchProjectData();
      console.log(`Data source "${dataSource.name}" deleted successfully`);
      
    } catch (error) {
      console.error('Error deleting data source:', error);
      alert(`Failed to delete data source: ${error.message}`);
    }
  };

  const handleDataSourceClick = (dataSource) => {
    const dsType = dataSource.type || dataSource.data_source?.type;
    
    // For external data sources (files), show DataGrid viewer
    if (dsType === 'external') {
      setSelectedDataSource(dataSource);
    } else {
      // For database data sources, show info
      const dsName = dataSource.name || dataSource.data_source?.name;
      alert(`Database data source: ${dsName}\nType: ${dsType}\n\nTo view tables, create a query using this data source.`);
    }
  };

  /* ───────────────── archive handlers ───────────────── */
  const handleQueryMenuClick = (query, event) => {
    event.stopPropagation();
    // Add archive status to the selected query
    const queryWithStatus = { ...query, is_archived: queryArchiveStatus[query.id] || false };
    setSelectedQuery(queryWithStatus);
    setQueryMenuAnchor(event.currentTarget);
  };

  const handleQueryMenuClose = () => {
    setQueryMenuAnchor(null);
  };

  const handleArchiveClick = () => {
    setQueryToArchive(selectedQuery);
    setArchiveDialogOpen(true);
    handleQueryMenuClose();
  };

  const handleArchiveConfirm = async () => {
    if (!queryToArchive) return;
    
    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/queries/${queryToArchive.id}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to archive query: ${response.status}`);
      }
      
      // Refresh the project data
      fetchProjectData();
      
      console.log(`Query "${queryToArchive.name}" archived successfully`);
      alert(`Query "${queryToArchive.name}" has been archived.`);
      
    } catch (error) {
      console.error('Error archiving query:', error);
      alert(`Failed to archive query: ${error.message}`);
    } finally {
      setArchiveDialogOpen(false);
      setQueryToArchive(null);
    }
  };

  const handleArchiveCancel = () => {
    setArchiveDialogOpen(false);
    setQueryToArchive(null);
  };

  const handleUnarchive = async (query, event) => {
    event.stopPropagation();
    
    const confirmUnarchive = window.confirm(`Restore query "${query.name}" from archive?`);
    if (!confirmUnarchive) return;
    
    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/queries/${query.id}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ is_archived: false }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to unarchive query: ${response.status}`);
      }
      
      // Refresh the project data
      fetchProjectData();
      
      console.log(`Query "${query.name}" unarchived successfully`);
      alert(`Query "${query.name}" has been restored.`);
      
    } catch (error) {
      console.error('Error unarchiving query:', error);
      alert(`Failed to unarchive query: ${error.message}`);
    }
  };

  /* ───────────────── data source menu handlers ───────────────── */
  const handleDataSourceMenuClick = (dataSource, event) => {
    event.stopPropagation();
    setSelectedDataSourceForMenu(dataSource);
    setDataSourceMenuAnchor(event.currentTarget);
  };

  const handleDataSourceMenuClose = () => {
    setDataSourceMenuAnchor(null);
  };

  /* ───────────────── restore handlers ───────────────── */
  const handleRestoreClick = (query, event) => {
    event.stopPropagation();
    setQueryToRestore(query);
    setRestoreDialogOpen(true);
  };

  const handleRestoreConfirm = async () => {
    if (!queryToRestore) return;
    
    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/queries/${queryToRestore.id}/archive`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to restore query: ${response.status}`);
      }
      
      // Refresh both project data and archived queries
      fetchProjectData();
      fetchArchivedQueries();
      
      console.log(`Query "${queryToRestore.name}" restored successfully`);
      alert(`Query "${queryToRestore.name}" has been restored.`);
      
    } catch (error) {
      console.error('Error restoring query:', error);
      alert(`Failed to restore query: ${error.message}`);
    } finally {
      setRestoreDialogOpen(false);
      setQueryToRestore(null);
    }
  };

  const handleRestoreCancel = () => {
    setRestoreDialogOpen(false);
    setQueryToRestore(null);
  };

  const handlePermanentDeleteFromArchive = async (query, event) => {
    event.stopPropagation();
    
    const confirmDelete = window.confirm(
      `Are you sure you want to PERMANENTLY delete the query "${query.name}"?\n\n` +
      `This action cannot be undone and will delete all associated visualizations, alerts, and widgets.`
    );
    
    if (!confirmDelete) return;
    
    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/queries/${query.id}/delete`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to delete query: ${response.status}`);
      }
      
      // Refresh archived queries list
      fetchArchivedQueries();
      
      console.log(`Query "${query.name}" permanently deleted`);
      alert(`Query "${query.name}" has been permanently deleted.`);
      
    } catch (error) {
      console.error('Error deleting query:', error);
      alert(`Failed to delete query: ${error.message}`);
    }
  };

  /* ───────────────── render ───────────────── */
  
  // If a data source is selected, show the DataSourceViewer
  if (selectedDataSource) {
    return (
      <DataSourceViewer
        dataSource={selectedDataSource}
        onBack={() => setSelectedDataSource(null)}
      />
    );
  }
  
  return (
    <div className="project-detail-page">
      <div className="project-detail-page__header">
        <h2 className="project-detail-page__title">{project.name}</h2>
        <div className="project-detail-page__actions">
          <ProjectFileUpload projectId={project.id} onUploadComplete={fetchProjectData} />
          <ProjectSettingsMenu projectId={project.id} />
        </div>
      </div>

      {/* Dashboards */}
      <section className="project-detail-page__section">
        <h3 className="project-detail-page__section-header">
          <IconButton
            size="small"
            title="Create new dashboard"
            className="project-detail-page__add-btn"
            onClick={() => {
              CreateDashboardDialog.showModal({ 
                projectId: projectId 
              }).result.then((dashboard) => {
                if (onDashboardSelected && dashboard && dashboard.slug) {
                  onDashboardSelected(dashboard.slug);
                } else if (dashboard && dashboard.slug) {
                  const orgSlug = getOrgSlug();
                  window.location.href = `/${orgSlug}/#dashboard/${dashboard.slug}`;
                }
                fetchProjectData();
              }).catch(() => {});
            }}
          >
            <AddBoxOutlinedIcon fontSize="small" />
          </IconButton>
          <span className="project-detail-page__section-title">Dashboards</span>
        </h3>

        {dashboards.length ? (
          <div className="project-detail-page__card-grid">
            {dashboards.map(d => (
              <div
                key={d.id}
                className="project-card"
                onClick={() => handleDashboardClick(d)}
              >
                <div className="project-card__header">
                  <h4 className="project-card__title">{d.name}</h4>
                  <IconButton
                    size="small"
                    title="Delete dashboard"
                    className="project-card__delete-btn"
                    onClick={(event) => handleDeleteDashboard(d, event)}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </div>
                <div className="project-card__divider" />
                <div className="project-card__label">Dashboard</div>
                <div className="project-card__value">{d.slug || 'N/A'}</div>
                <div className="project-card__meta">
                  <div className="project-card__meta-item">Created on: {formatDate(d.created_at)}</div>
                  <div className="project-card__meta-item">Created by: {(d.user && d.user.name) || d.created_by || 'Unknown'}</div>
                  <div className="project-card__meta-item">Last updated: {formatDate(d.updated_at)}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="project-detail-page__empty">No dashboards found.</p>
        )}
      </section>

      {/* Queries */}
      <section className="project-detail-page__section">
        <h3 className="project-detail-page__section-header">
          <IconButton
            size="small"
            title="Create new query"
            className="project-detail-page__add-btn"
            onClick={() => {
              document.dispatchEvent(
                new CustomEvent('openCodeEditor', { detail: { queryId: 'new' } }),
              );
            }}
          >
            <AddBoxOutlinedIcon fontSize="small" />
          </IconButton>
          <span className="project-detail-page__section-title">Queries</span>
        </h3>

        {queries.length ? (
          <div className="project-detail-page__card-grid">
            {queries.map(q => (
              <div
                key={q.id}
                className="project-card"
                onClick={() => handleQueryClick(q)}
              >
                <div className="project-card__header">
                  <h4 className="project-card__title">
                    {q.name}
                    {queryArchiveStatus[q.id] && (
                      <span className="project-card__badge project-card__badge--archived">
                        Archived
                      </span>
                    )}
                  </h4>
                  <IconButton
                    size="small"
                    title="Query options"
                    className="project-card__menu-btn"
                    onClick={(event) => handleQueryMenuClick(q, event)}
                  >
                    <MoreVertIcon fontSize="small" />
                  </IconButton>
                </div>
                <div className="project-card__divider" />
                <div className="project-card__label">Source File</div>
                <div className="project-card__value">{q.data_source || q.name}</div>
                <div className="project-card__meta">
                  <div className="project-card__meta-item">Created on: {formatDate(q.created_at)}</div>
                  <div className="project-card__meta-item">Created by: {q.created_by || (q.user && q.user.name) || 'Unknown'}</div>
                  <div className="project-card__meta-item">Last updated: {formatDate(q.updated_at)}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="project-detail-page__empty">No queries found.</p>
        )}
      </section>

      {/* Data Sources */}
      <section className="project-detail-page__section">
        <h3 className="project-detail-page__section-header">
          <span className="project-detail-page__section-title">Data Sources</span>
        </h3>

        {data_sources.length ? (
          <div className="project-detail-page__card-grid">
            {data_sources.map(ds => {
              const dsType = ds.type || ds.data_source?.type;
              const isExternal = dsType === 'external';
              
              return (
                <div
                  key={ds.data_source_id || ds.id}
                  className={`project-card ${isExternal ? '' : 'project-card--non-interactive'}`}
                  onClick={() => isExternal && handleDataSourceClick(ds)}
                >
                  <div className="project-card__header">
                    <h4 className="project-card__title">
                      {ds.name || ds.data_source?.name}
                      {isExternal && (
                        <span className="project-card__click-hint">(click to view)</span>
                      )}
                    </h4>
                    <IconButton
                      size="small"
                      title="Data source options"
                      className="project-card__menu-btn"
                      onClick={(event) => handleDataSourceMenuClick(ds, event)}
                    >
                      <MoreVertIcon fontSize="small" />
                    </IconButton>
                  </div>
                  <div className="project-card__divider" />
                  <div className="project-card__label">Type</div>
                  <div className="project-card__value">
                    {dsType || 'N/A'}
                    {isExternal && (
                      <span className="project-card__badge project-card__badge--external" style={{ marginLeft: '8px' }}>
                        📄 File
                      </span>
                    )}
                  </div>
                  <div className="project-card__meta">
                    <div className="project-card__meta-item">Created on: {formatDate(ds.created_at || ds.data_source?.created_at)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="project-detail-page__empty">No data sources found.</p>
        )}
      </section>

      <DeleteDataSourceDialog
        open={deleteDialogOpen}
        dataSource={dataSourceToDelete}
        onClose={() => {
          setDeleteDialogOpen(false);
          setDataSourceToDelete(null);
        }}
        onConfirm={confirmDeleteDataSource}
      />

      {/* Query Menu */}
      <Menu
        anchorEl={queryMenuAnchor}
        open={Boolean(queryMenuAnchor)}
        onClose={handleQueryMenuClose}
      >
        <MenuItem onClick={() => {
          handleRemoveQuery(selectedQuery, { stopPropagation: () => {} });
          handleQueryMenuClose();
        }}>
          <VisibilityOffIcon style={{ marginRight: 8 }} />
          Remove
        </MenuItem>
        
        {!selectedQuery?.is_archived ? (
          <MenuItem onClick={handleArchiveClick}>
            <ArchiveIcon style={{ marginRight: 8 }} />
            Archive Query
          </MenuItem>
        ) : (
          <>
            <MenuItem onClick={() => {
              handleUnarchive(selectedQuery, { stopPropagation: () => {} });
              handleQueryMenuClose();
            }}>
              <UnarchiveIcon style={{ marginRight: 8, color: '#4CAF50' }} />
              Unarchive
            </MenuItem>
            <MenuItem onClick={() => {
              handleDeleteQuery(selectedQuery, { stopPropagation: () => {} });
              handleQueryMenuClose();
            }}>
              <DeleteIcon style={{ marginRight: 8 }} />
              Delete Permanently
            </MenuItem>
          </>
        )}
      </Menu>

      {/* Data Source Menu */}
      <Menu
        anchorEl={dataSourceMenuAnchor}
        open={Boolean(dataSourceMenuAnchor)}
        onClose={handleDataSourceMenuClose}
      >
        <MenuItem onClick={() => {
          handleRemoveDataSource(selectedDataSourceForMenu, { stopPropagation: () => {} });
          handleDataSourceMenuClose();
        }}>
          <VisibilityOffIcon style={{ marginRight: 8 }} />
          Remove
        </MenuItem>
        
        <MenuItem onClick={() => {
          handleDeleteDataSource(selectedDataSourceForMenu, { stopPropagation: () => {} });
          handleDataSourceMenuClose();
        }}>
          <DeleteIcon style={{ marginRight: 8 }} />
          Delete Permanently
        </MenuItem>
      </Menu>

      {/* Archive Confirmation Dialog */}
      <Dialog open={archiveDialogOpen} onClose={handleArchiveCancel}>
        <DialogTitle>Archive Query?</DialogTitle>
        <DialogContent>
          <Typography>
            "{queryToArchive?.name}" will be archived and removed from this project.
          </Typography>
          <Typography variant="body2" color="textSecondary" style={{ marginTop: 8 }}>
            You can restore it from the Archived Queries section in the left sidebar.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleArchiveCancel}>Cancel</Button>
          <Button onClick={handleArchiveConfirm} color="primary">
            Archive
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

ProjectDetailPage.propTypes = {
  projectId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  onQuerySelected: PropTypes.func,
  onDashboardSelected: PropTypes.func,
};

ProjectDetailPage.defaultProps = {
  onQuerySelected: null,
  onDashboardSelected: null,
};
