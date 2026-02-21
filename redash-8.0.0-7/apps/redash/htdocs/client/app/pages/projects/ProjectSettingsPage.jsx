import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { react2angular } from 'react2angular';
import Button from 'antd/lib/button';
import Spin from 'antd/lib/spin';
import notification from '@/services/notification';
import SettingsSidebar from '@/components/projects/SettingsSidebar';
import MemberManagementPanel from '@/components/projects/MemberManagementPanel';
import NavigationPane from '@/pages/NavigationPane/NavigationPane';
import { routesToAngularRoutes } from '@/lib/utils';
import './ProjectSettingsPage.less';

/**
 * Helper function to extract organization slug from URL
 * @returns {string} Organization slug or 'default' if not found
 */
const getOrgSlug = () => window.location.pathname.split('/')[1] || 'default';

/**
 * ProjectSettingsPage Component
 * 
 * Main container for project settings with sidebar navigation.
 * Manages active section and renders appropriate content panel.
 */
function ProjectSettingsPage({ projectId: propProjectId, initialSection: propInitialSection }) {
  // Extract projectId from URL if not provided as prop
  const getProjectIdFromUrl = () => {
    const match = window.location.pathname.match(/\/projects\/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  };

  const projectId = propProjectId || getProjectIdFromUrl();
  const initialSection = propInitialSection || window.location.pathname.split('/').pop() || 'members';

  const [project, setProject] = useState(null);
  const [currentSection, setCurrentSection] = useState(initialSection);
  const [loading, setLoading] = useState(true);
  const [userRole, setUserRole] = useState(null);
  
  // Navigation state for NavigationPane
  const [selectedProjectId, setSelectedProjectId] = useState(projectId);
  const [selectedQueryId, setSelectedQueryId] = useState(null);
  const [codeMode, setCodeMode] = useState(false);
  const [selectedDashboardSlug, setSelectedDashboardSlug] = useState(null);
  const [selectedDataSource, setSelectedDataSource] = useState(null);
  const [showUsersView, setShowUsersView] = useState(false);

  // Debug logging
  useEffect(() => {
    console.log('[ProjectSettingsPage] Component mounted:', { 
      propProjectId, 
      extractedProjectId: getProjectIdFromUrl(),
      finalProjectId: projectId,
      initialSection,
      url: window.location.pathname
    });
  }, []);

  useEffect(() => {
    if (projectId && !isNaN(projectId)) {
      loadProject();
    } else {
      console.error('[ProjectSettingsPage] Invalid projectId:', projectId);
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    // Update page title when section or project changes
    if (project) {
      document.title = `${project.name} - Settings - TableScope`;
    }
    
    // Sync navigation state with current projectId
    if (projectId) {
      setSelectedProjectId(projectId);
    }
  }, [currentSection, project, projectId]);

  const loadProject = async () => {
    if (!projectId || isNaN(projectId)) {
      notification.error('Invalid project ID');
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      console.log('[ProjectSettingsPage] Fetching project:', projectId);
      const url = `api/projects/${projectId}`;
      console.log('[ProjectSettingsPage] Fetching from URL:', url);
      const response = await fetch(url, {
        credentials: 'same-origin',
      });

      console.log('[ProjectSettingsPage] Response status:', response.status, response.statusText);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('[ProjectSettingsPage] Error response:', errorText);
        throw new Error(`Failed to load project: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      console.log('[ProjectSettingsPage] Project data loaded:', data);
      setProject(data);

      // Determine user's role in the project
      await determineUserRole(projectId);
      
      // Stop loading after everything is done
      setLoading(false);
    } catch (error) {
      notification.error(`Failed to load project: ${error.message}`);
      console.error('Error loading project:', error);
      setLoading(false);
    }
  };

  const determineUserRole = async (projId) => {
    try {
      console.log('[ProjectSettingsPage] Determining user role for project:', projId);
      // Fetch project members to find current user's role
      const response = await fetch(`api/projects/${projId}/members`, {
        credentials: 'same-origin',
      });

      console.log('[ProjectSettingsPage] Members response status:', response.status);

      if (!response.ok) {
        throw new Error('Failed to load members');
      }

      const members = await response.json();
      console.log('[ProjectSettingsPage] Members loaded:', members);
      
      // Get current user ID from Angular's currentUser service
      // Try multiple ways to get the current user
      let currentUserId = null;
      
      // Method 1: Check if Angular injector is available
      if (window.angular) {
        try {
          const injector = window.angular.element(document.body).injector();
          if (injector) {
            const currentUser = injector.get('currentUser');
            currentUserId = currentUser?.id;
            console.log('[ProjectSettingsPage] Current user from Angular:', currentUser);
          }
        } catch (e) {
          console.log('[ProjectSettingsPage] Could not get currentUser from Angular:', e);
        }
      }
      
      // Method 2: Check window.currentUser (might be set globally)
      if (!currentUserId && window.currentUser) {
        currentUserId = window.currentUser.id;
      }
      
      console.log('[ProjectSettingsPage] Current user ID:', currentUserId);
      
      if (currentUserId) {
        const currentMember = members.find((m) => m.user_id === currentUserId);
        console.log('[ProjectSettingsPage] Current member:', currentMember);
        if (currentMember) {
          console.log('[ProjectSettingsPage] Setting user role to:', currentMember.role);
          setUserRole(currentMember.role);
        } else {
          // User is not a member, might be org admin - check if they have admin permission
          if (window.angular) {
            try {
              const injector = window.angular.element(document.body).injector();
              const currentUser = injector.get('currentUser');
              if (currentUser?.isAdmin) {
                console.log('[ProjectSettingsPage] User is org admin, setting role to admin');
                setUserRole('admin');
                return;
              }
            } catch (e) {
              // Ignore
            }
          }
          console.log('[ProjectSettingsPage] User not a member, defaulting to member role');
          setUserRole('member');
        }
      } else {
        console.log('[ProjectSettingsPage] No current user ID, defaulting to member role');
        setUserRole('member');
      }
    } catch (error) {
      console.error('Error determining user role:', error);
      setUserRole('member'); // Default to member on error
    }
  };

  const handleSectionChange = (section) => {
    setCurrentSection(section);
  };

  const handleBackClick = () => {
    console.log('[ProjectSettingsPage] ========== BACK BUTTON CLICKED ==========');
    console.log('[ProjectSettingsPage] Current URL:', window.location.href);
    console.log('[ProjectSettingsPage] Current pathname:', window.location.pathname);
    
    // Validate projectId
    if (!projectId || isNaN(projectId)) {
      console.error('[ProjectSettingsPage] Invalid projectId for navigation:', projectId);
      notification.error('Invalid project ID.');
      window.history.back();
      return;
    }

    console.log('[ProjectSettingsPage] Project ID to navigate to:', projectId);
    console.log('[ProjectSettingsPage] Project data:', project);
    
    // Get org slug
    const orgSlug = getOrgSlug();
    console.log('[ProjectSettingsPage] Org slug:', orgSlug);
    
    // CRITICAL: Store projectId in localStorage so home page can pick it up
    try {
      localStorage.setItem('__pendingProjectSelection', projectId.toString());
      console.log('[ProjectSettingsPage] Stored projectId in localStorage');
    } catch (e) {
      console.error('[ProjectSettingsPage] Failed to store in localStorage:', e);
    }
    
    // Set multiple global state variables
    window.__currentProjectId = projectId;
    window.__selectedProjectId = projectId;
    window.__pendingProjectSelection = projectId;
    console.log('[ProjectSettingsPage] Set global state variables');
    
    // Try to use Angular's $location service to navigate
    try {
      if (window.angular) {
        const injector = window.angular.element(document.body).injector();
        if (injector) {
          const $location = injector.get('$location');
          const $rootScope = injector.get('$rootScope');
          
          console.log('[ProjectSettingsPage] Current Angular location:', $location.path());
          console.log('[ProjectSettingsPage] Current Angular url:', $location.url());
          
          // Navigate to home page using Angular routing
          const targetPath = `/${orgSlug}`;
          console.log('[ProjectSettingsPage] Navigating to:', targetPath);
          
          $location.path(targetPath);
          $location.replace(); // Don't add to history
          
          // Force digest cycle
          $rootScope.$applyAsync();
          
          console.log('[ProjectSettingsPage] Navigation initiated via Angular $location');
          return;
        }
      }
    } catch (error) {
      console.error('[ProjectSettingsPage] Angular navigation failed:', error);
    }
    
    // Fallback: direct navigation
    console.log('[ProjectSettingsPage] Using fallback: direct navigation');
    window.location.assign(`/${orgSlug}`);
  };

  // Define available settings sections
  const sections = [
    {
      id: 'members',
      label: 'Members',
      icon: 'fa fa-users',
    },
    // Future sections can be added here:
    // { id: 'general', label: 'General', icon: 'fa fa-cog' },
    // { id: 'advanced', label: 'Advanced', icon: 'fa fa-sliders' },
  ];

  // Render content based on active section
  const renderContent = () => {
    if (!userRole) {
      return (
        <div className="loading-container">
          <Spin size="large" />
        </div>
      );
    }

    switch (currentSection) {
      case 'members':
        return <MemberManagementPanel projectId={projectId} userRole={userRole} />;
      case 'general':
        return (
          <div className="placeholder-content">
            <h3>General Settings</h3>
            <p>General project settings will be available here.</p>
          </div>
        );
      case 'advanced':
        return (
          <div className="placeholder-content">
            <h3>Advanced Settings</h3>
            <p>Advanced project settings will be available here.</p>
          </div>
        );
      default:
        return (
          <div className="placeholder-content">
            <h3>Section Not Found</h3>
            <p>The requested settings section does not exist.</p>
          </div>
        );
    }
  };

  if (loading) {
    return (
      <div className="project-settings-page loading">
        <Spin size="large" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="project-settings-page error">
        <h2>Project Not Found</h2>
        <p>The requested project could not be loaded.</p>
        <Button onClick={handleBackClick}>Go Back</Button>
      </div>
    );
  }

  return (
    <div className="app-layout">
      <NavigationPane
        selectedProjectId={selectedProjectId}
        selectedQueryId={selectedQueryId}
        codeMode={codeMode}
        selectedDashboardSlug={selectedDashboardSlug}
        selectedDataSource={selectedDataSource}
        showUsersView={showUsersView}
        onProjectSelect={setSelectedProjectId}
        onQuerySelect={setSelectedQueryId}
        onCodeModeChange={setCodeMode}
        onDashboardSelect={setSelectedDashboardSlug}
        onDataSourceSelect={setSelectedDataSource}
        onUsersViewChange={setShowUsersView}
      />
      
      <div className="main-content">
        <div className="project-settings-page">
          <div className="settings-header">
            <Button
              type="link"
              icon={<i className="fa fa-arrow-left" />}
              onClick={handleBackClick}
              className="back-button"
            >
              Back to Project
            </Button>
            <h1 className="settings-title">{project.name} Settings</h1>
          </div>

          <div className="settings-layout">
            <div className="settings-sidebar-container">
              <SettingsSidebar
                sections={sections}
                activeSection={currentSection}
                onSectionChange={handleSectionChange}
              />
            </div>

            <div className="settings-content-container">
              {renderContent()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

ProjectSettingsPage.propTypes = {
  projectId: PropTypes.number,
  initialSection: PropTypes.string,
};

ProjectSettingsPage.defaultProps = {
  projectId: null,
  initialSection: 'members',
};

export default function init(ngModule) {
  ngModule.component(
    'pageProjectSettings',
    react2angular(ProjectSettingsPage, ['projectId', 'initialSection'])
  );

  return routesToAngularRoutes(
    [
      {
        path: '/projects/:projectId/settings',
        title: 'Project Settings',
        key: 'project_settings',
      },
      {
        path: '/projects/:projectId/settings/:section',
        title: 'Project Settings',
        key: 'project_settings_section',
      },
    ],
    {
      reloadOnSearch: false,
      template: '<page-project-settings project-id="$resolve.projectId" initial-section="$resolve.initialSection"></page-project-settings>',
      controller($scope, $route, $routeParams) {
        'ngInject';

        const projectId = parseInt($routeParams.projectId, 10);
        const initialSection = $routeParams.section || 'members';

        console.log('[ProjectSettingsPage] Route params:', { projectId, initialSection, $routeParams });

        $scope.$resolve = {
          projectId: projectId,
          initialSection: initialSection,
        };
      },
    }
  );
}

init.init = true;
