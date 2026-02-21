/* eslint-disable react/require-default-props, camelcase, react/sort-comp */

import PropTypes from 'prop-types';
import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import angular from 'angular';
import Tooltip from '@material-ui/core/Tooltip';
import CreateNewFolderOutlinedIcon from '@material-ui/icons/CreateNewFolderOutlined';
import ViewModuleOutlinedIcon from '@material-ui/icons/ViewModuleOutlined';

import AddMembersDialog from '@/components/projects/AddMembersDialog';
import EditProjectsDialog from '@/components/EditProjectsDialog';
import EditQueriesDialog from '@/components/EditQueriesDialog';
import EditDataSourcesDialog from '@/components/EditDataSourcesDialog';

import { currentUser as authCurrentUser } from '@/services/auth';
import { User } from '@/services/user';
import { Project } from '@/services/project';

import notification from 'antd/lib/notification';

/* ------------------------------------------------------------ */
/* Helpers                                                      */
/* ------------------------------------------------------------ */

/* ------------------------------------------------------------ */
/* Project actions menu                                          */
/* ------------------------------------------------------------ */
function ProjectActionsMenu({ isVisible, onRename, onDelete, onAddMembers, onAddQuery, onAddDataSource }) {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setIsOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [isOpen]);

  const handle = fn => {
    if (fn) fn();
    setIsOpen(false);
  };

  return (
    <div ref={ref} style={{ position: 'relative', marginLeft: 'auto' }}>
      <button
        type="button"
        className={`navigation-pane__action-menu-btn project-action-button ${isVisible ? '' : 'hidden'}`}
        style={{ visibility: isVisible ? 'visible' : 'hidden' }}
        aria-label="More options"
        onClick={e => {
          e.stopPropagation();
          setIsOpen(p => !p);
        }}
      >
        &#x2026;
      </button>

      {isOpen && (
        <div className="navigation-pane__dropdown" role="menu" onClick={e => e.stopPropagation()}>
          <ul className="navigation-pane__dropdown-list">
            <li>
              <button type="button" className="navigation-pane__dropdown-item" onClick={() => handle(onAddQuery)}>
                Add Query
              </button>
            </li>
            <li>
              <button type="button" className="navigation-pane__dropdown-item" onClick={() => handle(onAddDataSource)}>
                Add DataSource
              </button>
            </li>
            <li>
              <button type="button" className="navigation-pane__dropdown-item" onClick={() => handle(onRename)}>
                Rename
              </button>
            </li>
            <li>
              <button
                type="button"
                className="navigation-pane__dropdown-item navigation-pane__dropdown-item--danger"
                onClick={() => handle(onDelete)}
              >
                Delete
              </button>
            </li>
            <li>
              <button type="button" className="navigation-pane__dropdown-item" onClick={() => handle(onAddMembers)}>
                Add members
              </button>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}

ProjectActionsMenu.propTypes = {
  isVisible: PropTypes.bool.isRequired,
  onRename: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onAddMembers: PropTypes.func.isRequired,
  onAddQuery: PropTypes.func.isRequired,
  onAddDataSource: PropTypes.func.isRequired,
};

/* ------------------------------------------------------------ */
/* Query actions menu                                            */
/* ------------------------------------------------------------ */
function QueryActionsMenu({ isVisible, onRename, onArchive, onUnarchive, onAddProject, isArchived }) {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setIsOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [isOpen]);

  const handle = fn => {
    if (fn) fn();
    setIsOpen(false);
  };

  return (
    <div ref={ref} style={{ position: 'relative', marginLeft: 'auto' }}>
      <button
        type="button"
        className={`navigation-pane__action-menu-btn query-action-button ${isVisible ? '' : 'hidden'}`}
        style={{ visibility: isVisible ? 'visible' : 'hidden' }}
        aria-label="More options"
        onClick={e => {
          e.stopPropagation();
          setIsOpen(p => !p);
        }}
      >
        &#x2026;
      </button>

      {isOpen && (
        <div className="navigation-pane__dropdown" role="menu" onClick={e => e.stopPropagation()}>
          <ul className="navigation-pane__dropdown-list">
            <li>
              <button type="button" className="navigation-pane__dropdown-item" onClick={() => handle(onAddProject)}>
                Add Project
              </button>
            </li>
            <li>
              <button type="button" className="navigation-pane__dropdown-item" onClick={() => handle(onRename)}>
                Rename
              </button>
            </li>
            {!isArchived ? (
              <li>
                <button
                  type="button"
                  className="navigation-pane__dropdown-item navigation-pane__dropdown-item--warning"
                  onClick={() => handle(onArchive)}
                >
                  Archive
                </button>
              </li>
            ) : (
              <li>
                <button
                  type="button"
                  className="navigation-pane__dropdown-item navigation-pane__dropdown-item--success"
                  onClick={() => handle(onUnarchive)}
                >
                  Unarchive
                </button>
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

QueryActionsMenu.propTypes = {
  isVisible: PropTypes.bool.isRequired,
  onRename: PropTypes.func.isRequired,
  onArchive: PropTypes.func.isRequired,
  onUnarchive: PropTypes.func.isRequired,
  onAddProject: PropTypes.func.isRequired,
  isArchived: PropTypes.bool,
};

/* ------------------------------------------------------------ */
/* Main component                                                */
/* ------------------------------------------------------------ */
export default function Navigation({
  http,
  onProjectSelected,
  onQuerySelected,
  onDataSourceSelected,
  createProject,
}) {
  const $http = useMemo(() => http || angular.injector(['ng']).get('$http'), [http]);
  const orgSlug = useMemo(
    () => window.location.pathname.split('/')[1] || 'default',
    [],
  );

  const [viewMode, setViewMode] = useState('projects');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [publicProjects, setPublic] = useState([]);
  const [privateProjects, setPrivate] = useState([]);
  const [queriesRaw, setQueriesRaw] = useState([]);
  const [unassignedQueries, setUnassignedQueries] = useState([]);
  const [sharedCollapsed, setSharedCollapsed] = useState(true);
  const [privateCollapsed, setPrivateCollapsed] = useState(true);
  const [hoveredPid, setHoveredPid] = useState(null);
  const [hoveredQid, setHoveredQid] = useState(null);
  // ★ Start collapsed on load:
  const [assignedCollapsed, setAssignedCollapsed] = useState(true);   // was false
  const [unassignedCollapsed, setUnassignedCollapsed] = useState(true); // was false
  const [privateDataSourcesCollapsed, setPrivateDataSourcesCollapsed] = useState(true);
  const [sharedDataSourcesCollapsed, setSharedDataSourcesCollapsed] = useState(true);
  const [enterpriseDataSourcesCollapsed, setEnterpriseDataSourcesCollapsed] = useState(true);
  const [privateDataSources, setPrivateDataSources] = useState([]);
  const [expandedDataSources, setExpandedDataSources] = useState({});
  const [dataSourceTables, setDataSourceTables] = useState({});
  const [tableSearchTerms, setTableSearchTerms] = useState({});
  const [sharedDataSources, setSharedDataSources] = useState([]);
  const [enterpriseDataSources, setEnterpriseDataSources] = useState([]);

  const [isMembersDialogOpen, setIsMembersDialogOpen] = useState(false);
  const [editingProject, setEditingProject] = useState(null);
  const [dialogData, setDialogData] = useState({ initialSelection: [], options: [], initialMemberIds: [] });
  const [queryArchiveStatus, setQueryArchiveStatus] = useState({});

  /* ------------------------- data fetchers -------------------------- */
  const fetchProjects = useCallback(async () => {
    if (!$http) return;
    try {
      const [pubRes, privRes] = await Promise.all([
        $http.get(`/${orgSlug}/api/public_projects`),
        $http.get(`/${orgSlug}/api/private_projects`),
      ]);
      setPublic(pubRes.data);
      setPrivate(privRes.data);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(err);
      setError('Failed to load project lists.');
    }
  }, [$http, orgSlug]);

  const fetchMyUnassignedQueries = useCallback(async () => {
    if (!$http) return;
    try {
      const res = await $http.get(`/${orgSlug}/api/my_unassigned_queries`);
      if (res.data && Array.isArray(res.data.results)) {
        setUnassignedQueries(res.data.results);
      }
    } catch (err) {
      console.error('[NavigationPane] Failed to load unassigned queries list', err);
    }
  }, [$http, orgSlug]);

  const fetchQueriesForProjects = useCallback(
    async (projects) => {
      if (!projects.length || !$http) {
        setQueriesRaw([]);
        return;
      }
      try {
        const urls = projects.map(p => `/${orgSlug}/api/projects/${p.id}/items`);
        const jsonArr = await Promise.all(
          urls.map(u => 
            $http.get(u).catch(err => {
              // If a project was just deleted, ignore 404 errors
              if (err.status === 404) {
                console.warn('[NavigationPane] Project not found (may have been deleted):', u);
                return { data: { queries: [] } };
              }
              throw err;
            })
          )
        );
        const all = [];
        const seen = new Set();
        jsonArr.forEach((r) => {
          (r.data.queries || []).forEach((q) => {
            if (!seen.has(q.id)) {
              seen.add(q.id);
              all.push(q);
            }
          });
        });
        setQueriesRaw(all);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error(err);
        setError('Failed to load queries for your projects.');
      }
    },
    [$http, orgSlug],
  );

  const fetchQueryArchiveStatus = useCallback(async (queries) => {
    if (!queries.length || !$http) return;
    try {
      const statusPromises = queries.map(q =>
        $http.get(`/${orgSlug}/api/queries/${q.id}`)
          .then(r => ({ id: q.id, is_archived: r.data?.is_archived || false }))
          .catch(() => ({ id: q.id, is_archived: false }))
      );
      
      const statuses = await Promise.all(statusPromises);
      const statusMap = {};
      statuses.forEach(s => {
        statusMap[s.id] = s.is_archived;
      });
      setQueryArchiveStatus(statusMap);
    } catch (err) {
      console.error('[NavigationPane] Failed to fetch query archive status', err);
    }
  }, [$http, orgSlug]);

  /**
   * Build a unique list of data sources (tables) from all queries the user can see.
   * Uses each query’s saved `data_source` when available, falls back to parsing SQL.
   */
  const fetchDataSourcesForUser = useCallback(async () => {
    if (!$http) return;
    try {
      const [privateRes, sharedRes, enterpriseRes] = await Promise.all([
        $http.get(`/${orgSlug}/api/private_data_sources`),
        $http.get(`/${orgSlug}/api/shared_data_sources`),
        $http.get(`/${orgSlug}/api/enterprise_data_sources`),
      ]);
      setPrivateDataSources(privateRes.data || []);
      setSharedDataSources(sharedRes.data || []);
      setEnterpriseDataSources(enterpriseRes.data || []);
    } catch (err) {
      console.error('[NavigationPane] Failed to load data sources', err);
      setPrivateDataSources([]);
      setSharedDataSources([]);
      setEnterpriseDataSources([]);
    }
  }, [$http, orgSlug]);

  const refreshAllData = useCallback(async () => {
    setLoading(true);
    await Promise.all([
      fetchProjects(),
      fetchMyUnassignedQueries(),
      fetchDataSourcesForUser(),
    ]);
    setLoading(false);
  }, [fetchProjects, fetchMyUnassignedQueries, fetchDataSourcesForUser]);

  useEffect(() => {
    refreshAllData();
  }, [refreshAllData]);

  // Listen for external refresh events (e.g., after project creation)
  useEffect(() => {
    const handleRefresh = () => {
      refreshAllData();
    };
    document.addEventListener('refresh-navigation', handleRefresh);
    return () => document.removeEventListener('refresh-navigation', handleRefresh);
  }, [refreshAllData]);

  useEffect(() => {
    fetchQueriesForProjects([...publicProjects, ...privateProjects]);
  }, [publicProjects, privateProjects, fetchQueriesForProjects]);

  // Load data sources when queries lists change
  useEffect(() => {
    fetchDataSourcesForUser();
  }, [fetchDataSourcesForUser]);

  // Fetch archive status when queries change
  useEffect(() => {
    const allQueries = [...queriesRaw, ...unassignedQueries];
    if (allQueries.length > 0) {
      fetchQueryArchiveStatus(allQueries);
    }
  }, [queriesRaw, unassignedQueries, fetchQueryArchiveStatus]);

  useEffect(() => {
    const handler = () => refreshAllData();
    document.addEventListener('project-created', handler);
    document.addEventListener('new-query-saved', handler);
    return () => {
      document.removeEventListener('project-created', handler);
      document.removeEventListener('new-query-saved', handler);
    };
  }, [refreshAllData]);

  /* --------------------------- handlers ----------------------------- */
  const handleProjectClick = (id) => {
    // Refresh data to ensure query list is up-to-date
    // This handles cases where backend operations (like unsharing) changed the data
    refreshAllData();
    
    if (onProjectSelected) onProjectSelected(id);
    else window.location.href = `/${orgSlug}/projects/${id}`;
  };

  const handleQueryClick = (id) => {
    if (onQuerySelected) onQuerySelected(id);
    else window.location.href = `/${orgSlug}/tsqueries/${id}#table`;
  };

  const openMembersDialog = async (project) => {
    try {
      const [proj, allUsersResponse] = await Promise.all([
        Project.get({ id: project.id }).$promise,
        User.query({ _: Date.now() }).$promise, // Add cache-busting parameter
      ]);

      let membersArray = [];
      if (Array.isArray(proj.members)) {
        membersArray = proj.members;
      } else if (proj.members && typeof proj.members === 'object') {
        membersArray = Object.values(proj.members);
      }

      // Build a map of member objects by user ID to get the correct user data
      const membersByUserId = new Map();
      membersArray.forEach(member => {
        const userId = member.id ?? member.user_id;
        if (userId && !membersByUserId.has(userId)) {
          membersByUserId.set(userId, member);
        }
      });

      const initialMemberIds = Array.from(membersByUserId.keys());
      const initialMemberIdsSet = new Set(initialMemberIds.map(String));

      const usersById = {};
      (allUsersResponse.results || []).forEach((u) => {
        usersById[String(u.id)] = u;
      });

      // Use the user data from the member object if available, otherwise look up from allUsers
      const existingMemberOptions = initialMemberIds.map((id) => {
        const member = membersByUserId.get(id);
        const userData = member?.user || member;
        const fallbackUser = usersById[String(id)] || {};
        const user = userData?.name ? userData : fallbackUser;
        
        return {
          value: String(id),
          label: user.name || user.email || `User #${id}`,
        };
      });

      // Include ALL users in options (both members and non-members)
      // The Select component needs all options to properly render labels with labelInValue
      const allUserOptions = (allUsersResponse.results || [])
        .map(user => ({
          value: String(user.id),
          label: user.name || user.email || `User #${user.id}`,
        }));

      allUserOptions.sort((a, b) => a.label.localeCompare(b.label));

      setDialogData({
        initialSelection: existingMemberOptions,
        options: allUserOptions, // Changed from availableUserOptions to allUserOptions
        initialMemberIds,
      });
      setEditingProject(project);
      setIsMembersDialogOpen(true);
    } catch (err) {
      notification.error({ message: err.message || 'Failed to load project data.' });
    }
  };

  const handleUpdateMembers = async (newMemberIds) => {
    if (!editingProject) return;

    try {
      const { initialMemberIds } = dialogData;
      const initialIdsNum = initialMemberIds.map(id => Number(id));
      const newIdsNum = (Array.isArray(newMemberIds) ? newMemberIds : []).map(id => Number(id));

      const initialSet = new Set(initialIdsNum);
      const newSet = new Set(newIdsNum);

      const membersToAdd = newIdsNum.filter(id => !initialSet.has(id));
      const membersToRemove = initialIdsNum.filter(id => !newSet.has(id));

      const apiPromises = [];
      membersToAdd.forEach((userId) => {
        apiPromises.push($http.post(`/${orgSlug}/api/projects/${editingProject.id}/members`, { user_id: userId }));
      });
      membersToRemove.forEach((userId) => {
        apiPromises.push($http.delete(`/${orgSlug}/api/projects/${editingProject.id}/members/${userId}`));
      });

      await Promise.all(apiPromises);
      notification.success({ message: 'Project members updated.' });
      await fetchProjects();
    } catch (err) {
      notification.error({ message: err.message || 'Failed to update members.' });
    } finally {
      setIsMembersDialogOpen(false);
      setEditingProject(null);
    }
  };

  const renameProject = async (project) => {
    const current = project.name;
    const newName = window.prompt('Rename project', current);
    if (!newName || !newName.trim() || newName === current) return;
    const payload = { name: newName.trim() };
    const endpoint = `/${orgSlug}/api/projects/${project.id}/rename`;

    try {
      await $http.post(endpoint, payload);
    } catch (err) {
      try {
        await $http.patch(endpoint, payload);
      } catch (err2) {
        console.error('[NavigationPane] renameProject error', err2);
        notification.error('Failed to rename project.');
        return;
      }
    }
    await refreshAllData();
    document.dispatchEvent(
      new CustomEvent('project-renamed', { detail: { id: project.id, name: newName.trim() } }),
    );
  };

  const deleteProject = async (project) => {
    const ok = window.confirm(`Are you sure you want to delete project "${project.name}"?`);
    if (!ok) return;
    try {
      await $http.delete(`/${orgSlug}/api/projects/${project.id}`);
      // Notify parent to clear selected project if it was the deleted one
      document.dispatchEvent(new CustomEvent('project-deleted', { detail: { projectId: project.id } }));
      await refreshAllData();
    } catch (err) {
      console.error(err);
      notification.error('Failed to delete project.');
    }
  };

  const renameQuery = async (query) => {
    const currentName = query.name;
    const newName = window.prompt('Rename query', currentName);
    if (!newName || !newName.trim() || newName === currentName) return;
    try {
      await $http.post(`/${orgSlug}/api/queries/${query.id}`, { name: newName.trim() });
      notification.success('Query renamed successfully.');
      await refreshAllData();
    } catch (err) {
      console.error('[NavigationPane] renameQuery error', err);
      notification.error('Failed to rename query.');
    }
  };

  const archiveQuery = async (query) => {
    const ok = window.confirm(`Are you sure you want to archive query "${query.name}"?\n\nYou can restore it from the Archived section.`);
    if (!ok) return;
    try {
      await $http.delete(`/${orgSlug}/api/queries/${query.id}`);
      notification.success('Query archived successfully.');
      await refreshAllData();
    } catch (err) {
      console.error('[NavigationPane] archiveQuery error', err);
      notification.error('Failed to archive query.');
    }
  };

  const restoreQuery = async (query) => {
    const ok = window.confirm(`Restore query "${query.name}"?`);
    if (!ok) return;
    try {
      await $http.post(`/${orgSlug}/api/queries/${query.id}`, { is_archived: false });
      notification.success('Query restored successfully.');
      await refreshAllData();
    } catch (err) {
      console.error('[NavigationPane] restoreQuery error', err);
      notification.error('Failed to restore query.');
    }
  };

  const permanentlyDeleteQuery = async (query) => {
    const ok = window.confirm(
      `Are you sure you want to PERMANENTLY delete query "${query.name}"?\n\n` +
      `This action cannot be undone and will delete all associated visualizations, alerts, and widgets.`
    );
    if (!ok) return;
    try {
      await $http.delete(`/${orgSlug}/api/queries/${query.id}/delete`);
      notification.success('Query permanently deleted.');
      await refreshAllData();
    } catch (err) {
      console.error('[NavigationPane] permanentlyDeleteQuery error', err);
      notification.error('Failed to delete query.');
    }
  };

  const addProjectToQuery = async (query) => {
    try {
      const queryDetailsRes = await $http.get(`/${orgSlug}/api/queries/${query.id}`);
      const queryDetails = queryDetailsRes.data;
      const currentProjectIds = queryDetails.project_id || [];

      EditProjectsDialog.showModal({
        queryId: query.id,
        projects: currentProjectIds,
        getAvailableProjects: () => $http.get(`/${orgSlug}/api/available_projects`).then(res => [
          ...(res.data.private_projects || []).map(p => ({ label: p.name, value: p.id })),
          ...(res.data.public_projects || []).map(p => ({ label: p.name, value: p.id })),
        ]),
      }).result.then((newProjectIds) => {
        $http.post(`/${orgSlug}/api/queries/${query.id}/projects`, { project_ids: newProjectIds })
          .then(() => {
            notification.success('Query projects updated successfully.');
            refreshAllData();
          })
          .catch(() => {
            notification.error('Failed to update query projects.');
          });
      });
    } catch (err) {
      notification.error('Failed to open "Add Project" dialog.');
      console.error(err);
    }
  };

  const addQueryToProject = async (project) => {
    try {
      // Get current project queries
      const projectRes = await $http.get(`/${orgSlug}/api/projects/${project.id}/items`);
      const currentQueries = projectRes.data.queries || [];
      const currentQueryIds = currentQueries.map(q => q.id);

      EditQueriesDialog.showModal({
        queries: currentQueryIds,
        queryNameMap: currentQueries.reduce((acc, x) => { acc[x.id] = x.name; return acc; }, {}),
        getAvailableQueries: () => $http.get(`/${orgSlug}/api/projects/${project.id}/available_queries`)
          .then(r => r.data.map(x => ({ label: x.name, value: x.id })))
          .catch(() => []),
      }).result.then((queryIds) => {
        $http.post(`/${orgSlug}/api/projects/${project.id}/available_queries`, { query_ids: queryIds })
          .then(() => {
            notification.success('Project queries updated successfully.');
            refreshAllData();
          })
          .catch(() => {
            notification.error('Failed to update project queries.');
          });
      });
    } catch (err) {
      notification.error('Failed to open "Add Query" dialog.');
      console.error(err);
    }
  };

  const addDataSourceToProject = async (project) => {
    try {
      // Get current project data sources
      const projectRes = await $http.get(`/${orgSlug}/api/projects/${project.id}/items`);
      const currentDataSources = projectRes.data.data_sources || [];
      const currentDataSourceIds = currentDataSources.map(ds => ds.data_source_id || ds.id);

      EditDataSourcesDialog.showModal({
        dataSources: currentDataSourceIds,
        dataSourceNameMap: currentDataSources.reduce((acc, x) => { 
          const id = x.data_source_id || x.id;
          const name = x.data_source?.name || x.name;
          acc[id] = name; 
          return acc; 
        }, {}),
        getAvailableDataSources: () => $http.get(`/${orgSlug}/api/data_sources`)
          .then(r => r.data.map(x => ({ label: x.name, value: x.id })))
          .catch(() => []),
      }).result.then((dataSourceIds) => {
        $http.post(`/${orgSlug}/api/projects/${project.id}/data_sources`, { data_source_ids: dataSourceIds })
          .then(() => {
            notification.success('Project data sources updated successfully.');
            refreshAllData();
          })
          .catch(() => {
            notification.error('Failed to update project data sources.');
          });
      });
    } catch (err) {
      notification.error('Failed to open "Add DataSource" dialog.');
      console.error(err);
    }
  };

  /* --------------------------- renderers ----------------------------- */

  const renderProjectList = (list, title, collapsed, setCollapsed) => (
    <div className="navigation-pane__section">
      <div
        className={`navigation-pane__section-header ${!collapsed ? 'navigation-pane__section-header--expanded' : ''}`}
        onClick={() => setCollapsed(p => !p)}
      >
        <span>{title}</span>
        <span className="navigation-pane__section-toggle">{collapsed ? '⌄' : '⌃'}</span>
      </div>
      {!collapsed && (
        <ul className="navigation-pane__list">
          {list.map(p => (
            <li
              key={p.id}
              className="navigation-pane__item"
              onMouseEnter={() => setHoveredPid(p.id)}
              onMouseLeave={() => setHoveredPid(null)}
            >
              <span
                className="navigation-pane__item-text"
                onClick={() => handleProjectClick(p.id)}
              >
                {p.name}
              </span>
              <ProjectActionsMenu
                isVisible={hoveredPid === p.id}
                onRename={() => renameProject(p)}
                onDelete={() => deleteProject(p)}
                onAddMembers={() => openMembersDialog(p)}
                onAddQuery={() => addQueryToProject(p)}
                onAddDataSource={() => addDataSourceToProject(p)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  const renderProjects = () => (
    <>
      {privateProjects.length > 0 &&
        renderProjectList(privateProjects, 'Private Projects', privateCollapsed, setPrivateCollapsed)}
      {publicProjects.length > 0 &&
        renderProjectList(publicProjects, 'Shared Projects', sharedCollapsed, setSharedCollapsed)}
    </>
  );

  const renderQueries = () => {
    const assignedQueries = queriesRaw;

    const renderQueryList = list => (
      <ul className="navigation-pane__list">
        {list.map(q => {
          const isArchived = queryArchiveStatus[q.id] || false;
          return (
            <li
              key={q.id}
              className={`navigation-pane__item ${isArchived ? 'navigation-pane__item--archived' : ''}`}
              onMouseEnter={() => setHoveredQid(q.id)}
              onMouseLeave={() => setHoveredQid(null)}
            >
              <span
                className="navigation-pane__item-text"
                onClick={() => handleQueryClick(q.id)}
              >
                {q.name}
                {isArchived && <span className="navigation-pane__archived-tag">(Archived)</span>}
              </span>
              <QueryActionsMenu
                isVisible={hoveredQid === q.id}
                isArchived={isArchived}
                onRename={() => renameQuery(q)}
                onArchive={() => archiveQuery(q)}
                onUnarchive={() => restoreQuery(q)}
                onAddProject={() => addProjectToQuery(q)}
              />
            </li>
          );
        })}
      </ul>
    );

    const header = (title, collapsed, toggle, count) => (
      <div
        className={`navigation-pane__section-header ${!collapsed ? 'navigation-pane__section-header--expanded' : ''}`}
        onClick={() => toggle(p => !p)}
      >
        <span>{title}{typeof count === 'number' ? ` (${count})` : ''}</span>
        <span className="navigation-pane__section-toggle">{collapsed ? '⌄' : '⌃'}</span>
      </div>
    );

    return (
      <div className="navigation-pane__section">
        {header('Project Assigned', assignedCollapsed, setAssignedCollapsed, assignedQueries.length)}
        {!assignedCollapsed && renderQueryList(assignedQueries)}

        {header('Not Assigned', unassignedCollapsed, setUnassignedCollapsed, unassignedQueries.length)}
        {!unassignedCollapsed && renderQueryList(unassignedQueries)}

        {assignedQueries.length === 0 && unassignedQueries.length === 0 && (
          <p className="navigation-pane__empty">No queries found.</p>
        )}
      </div>
    );
  };

  const fetchTablesForDataSource = async (dataSourceId) => {
    try {
      const response = await $http.get(`/${orgSlug}/api/data_sources/${dataSourceId}/schema`);
      if (response.data && response.data.schema) {
        // Extract table names from schema
        const tables = response.data.schema.map(table => ({
          name: table.name,
          columns: table.columns || []
        }));
        setDataSourceTables(prev => ({
          ...prev,
          [dataSourceId]: tables
        }));
      }
    } catch (error) {
      console.error('Error fetching tables for datasource:', error);
      setDataSourceTables(prev => ({
        ...prev,
        [dataSourceId]: []
      }));
    }
  };

  const handleDataSourceClick = (dataSource) => {
    const dsType = dataSource.type;
    
    // For external data sources (files), show DataGrid viewer
    if (dsType === 'external') {
      if (onDataSourceSelected) {
        onDataSourceSelected(dataSource);
      }
    } else {
      // For database data sources, toggle expansion and fetch tables
      const isExpanded = expandedDataSources[dataSource.id];
      setExpandedDataSources(prev => ({
        ...prev,
        [dataSource.id]: !isExpanded
      }));
      
      // Fetch tables if expanding and not already fetched
      if (!isExpanded && !dataSourceTables[dataSource.id]) {
        fetchTablesForDataSource(dataSource.id);
      }
    }
  };

  const handleTableClick = (dataSource, table) => {
    // Create a table object that looks like a datasource for the viewer
    const tableDataSource = {
      id: dataSource.id,
      name: dataSource.name,
      type: dataSource.type,
      tableName: table.name,
      isTable: true
    };
    
    if (onDataSourceSelected) {
      onDataSourceSelected(tableDataSource);
    }
  };

  const renderDataSources = () => {
    const renderDataSourceList = (list) => (
      <ul className="navigation-pane__list">
        {list.map(ds => {
          const isExternal = ds.type === 'external';
          const isDatabase = !isExternal;
          const isOpen = expandedDataSources[ds.id];
          const tables = dataSourceTables[ds.id] || [];
          const searchTerm = tableSearchTerms[ds.id] || '';
          
          // Filter tables based on search
          const filteredTables = tables.filter(table => 
            table.name.toLowerCase().includes(searchTerm.toLowerCase())
          );
          
          return (
            <li key={ds.id}>
              <div
                className="navigation-pane__item"
                onClick={() => handleDataSourceClick(ds)}
              >
                <span className="navigation-pane__item-text">
                  {ds.name}
                  {isExternal && (
                    <span className="navigation-pane__type-icon">📄</span>
                  )}
                  {isDatabase && (
                    <span className="navigation-pane__type-icon">
                      🗄️ {isOpen ? '▼' : '▶'}
                    </span>
                  )}
                </span>
              </div>
              
              {/* Show dropdown for database datasource when open */}
              {isDatabase && isOpen && (
                <div className="navigation-pane__expansion-panel">
                  {/* Search input */}
                  <input
                    type="text"
                    className="navigation-pane__search-input"
                    placeholder="🔍 Search tables..."
                    value={searchTerm}
                    onChange={(e) => {
                      e.stopPropagation();
                      setTableSearchTerms(prev => ({
                        ...prev,
                        [ds.id]: e.target.value
                      }));
                    }}
                    onClick={(e) => e.stopPropagation()}
                  />
                  
                  {/* Table list */}
                  <div className="navigation-pane__table-list">
                    {tables.length === 0 ? (
                      <div className="navigation-pane__empty">Loading tables...</div>
                    ) : filteredTables.length === 0 ? (
                      <div className="navigation-pane__empty">No tables found</div>
                    ) : (
                      filteredTables.map(table => (
                        <div
                          key={table.name}
                          className="navigation-pane__table-item"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleTableClick(ds, table);
                          }}
                        >
                          📊 {table.name}
                        </div>
                      ))
                    )}
                  </div>
                  
                  {/* Footer with count */}
                  {tables.length > 0 && (
                    <div className="navigation-pane__table-count">
                      {filteredTables.length} of {tables.length} tables
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    );

    const header = (title, collapsed, toggle, count) => (
      <div
        className={`navigation-pane__section-header ${!collapsed ? 'navigation-pane__section-header--expanded' : ''}`}
        onClick={() => toggle(p => !p)}
      >
        <span>{title}{typeof count === 'number' ? ` (${count})` : ''}</span>
        <span className="navigation-pane__section-toggle">{collapsed ? '⌄' : '⌃'}</span>
      </div>
    );

    return (
      <div className="navigation-pane__section">
        {privateDataSources.length > 0 && (
          <>
            {header('Private Data Sources', privateDataSourcesCollapsed, setPrivateDataSourcesCollapsed, privateDataSources.length)}
            {!privateDataSourcesCollapsed && renderDataSourceList(privateDataSources)}
          </>
        )}

        {sharedDataSources.length > 0 && (
          <>
            {header('Shared Data Sources', sharedDataSourcesCollapsed, setSharedDataSourcesCollapsed, sharedDataSources.length)}
            {!sharedDataSourcesCollapsed && renderDataSourceList(sharedDataSources)}
          </>
        )}

        {enterpriseDataSources.length > 0 && (
          <>
            {header('Enterprise Data Sources', enterpriseDataSourcesCollapsed, setEnterpriseDataSourcesCollapsed, enterpriseDataSources.length)}
            {!enterpriseDataSourcesCollapsed && renderDataSourceList(enterpriseDataSources)}
          </>
        )}

        {privateDataSources.length === 0 && sharedDataSources.length === 0 && enterpriseDataSources.length === 0 && (
          <p className="navigation-pane__empty">No data sources found.</p>
        )}
      </div>
    );
  };

  /* ----------------------------- render ------------------------------ */
  if (loading) return <div className="navigation-pane__loading">Loading navigation…</div>;
  if (error) return <div className="navigation-pane__error">Error: {error}</div>;

  const user = authCurrentUser || window.currentUser || { isAdmin: false };

  return (
    <nav className="navigation-pane">
      <h3 className="navigation-pane__header">
        {viewMode.charAt(0).toUpperCase() + viewMode.slice(1)}
      </h3>

      <div className="navigation-pane__tabs">
        <button 
          type="button" 
          className={`navigation-pane__tab ${viewMode === 'projects' ? 'navigation-pane__tab--active' : ''}`}
          onClick={() => setViewMode('projects')}
        >
          Projects
        </button>
        <button 
          type="button" 
          className={`navigation-pane__tab ${viewMode === 'queries' ? 'navigation-pane__tab--active' : ''}`}
          onClick={() => setViewMode('queries')}
        >
          Queries
        </button>
        <button 
          type="button" 
          className={`navigation-pane__tab ${viewMode === 'datasources' ? 'navigation-pane__tab--active' : ''}`}
          onClick={() => setViewMode('datasources')}
        >
          Data Sources
        </button>
      </div>

      {viewMode === 'projects' && (
        <>
          <Tooltip title="Create New Project" placement="right" arrow>
            <button
              type="button"
              className="navigation-pane__action-btn"
              onClick={() => createProject && createProject()}
            >
              <span>+New Project</span>
            </button>
          </Tooltip>
          <div className="navigation-pane__divider" />
        </>
      )}

      {viewMode === 'queries' && user.isAdmin && (
        <Tooltip title="New Query" placement="right" arrow>
          <button
            type="button"
            className="navigation-pane__action-btn"
            onClick={() => {
              document.dispatchEvent(
                new CustomEvent('openCodeEditor', { detail: { queryId: 'new' } }),
              );
            }}
          >
            <ViewModuleOutlinedIcon fontSize="large" />
            <span>New Query</span>
          </button>
        </Tooltip>
      )}

      {viewMode === 'projects' && renderProjects()}
      {viewMode === 'queries' && renderQueries()}
      {viewMode === 'datasources' && renderDataSources()}

      {isMembersDialogOpen && (
        <AddMembersDialog
          visible={isMembersDialogOpen}
          initialSelection={dialogData.initialSelection}
          options={dialogData.options}
          onOk={handleUpdateMembers}
          onCancel={() => setIsMembersDialogOpen(false)}
        />
      )}
    </nav>
  );
}

Navigation.propTypes = {
  http: PropTypes.func,
  onProjectSelected: PropTypes.func,
  onQuerySelected: PropTypes.func,
  createProject: PropTypes.func,
};

Navigation.defaultProps = {
  http: null,
  onProjectSelected: null,
  onQuerySelected: null,
  createProject: null,
};
