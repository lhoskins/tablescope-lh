import angular from 'angular';
import settingsMenu from '@/services/settingsMenu';

function MyApprovalsController($scope, $http, $log, $timeout) {
  'ngInject';

  $scope.approvals = [];
  $scope.requests = [];
  $scope.loading = false;
  $scope.errorMessage = '';
  $scope.successMessage = ''; // For popup notifications
  $scope.selectAllChecked = false;
  $scope.activeTab = 'approvals'; // Default tab

  // Function to display success messages temporarily
  function showPopupMessage(message) {
    $scope.successMessage = message;
    $timeout(() => {
      $scope.successMessage = ''; // Clear the message after 5 seconds
    }, 5000);
  }

  // Fetch approvals from the API
  function fetchApprovals() {
    $log.debug('Fetching approvals...');
    $scope.loading = true;

    const orgSlug = window.location.pathname.split('/')[1] || 'default';
    const apiUrl = `/${orgSlug}/api/my_approvals`;

    $http.get(apiUrl)
      .then((response) => {
        $log.debug('Approvals fetched successfully:', response.data);
        $scope.approvals = response.data.map(approval => ({
          ...approval,
          type: approval.approval_type || 'N/A', // Map type to approval_type
          projectOrGroupName: approval.approval_type === 'Group' ? approval.group_name : approval.project_name || 'N/A', // Dynamically map group_name or project_name
          requester: approval.data_source_owner_name || 'N/A',
          selected: false,
        }));
      })
      .catch((error) => {
        $log.error('Error fetching approvals:', error);
        $scope.errorMessage = 'Error fetching approvals. Please try again later.';
      })
      .finally(() => {
        $scope.loading = false;
      });
  }

  // Fetch requests from the API
  function fetchRequests() {
    $log.debug('Fetching requests...');
    $scope.loading = true;

    const orgSlug = window.location.pathname.split('/')[1] || 'default';
    const apiUrl = `/${orgSlug}/api/my_requests`;

    $http.get(apiUrl)
      .then((response) => {
        $log.debug('Requests fetched successfully:', response.data);
        $scope.requests = response.data.map(request => ({
          ...request,
          type: request.approval_type || 'N/A', // Map type to approval_type
          projectOrGroupName: request.approval_type === 'Group' ? request.group_name : request.project_name || 'N/A', // Dynamically map group_name or project_name
          owner: request.approver_name || 'N/A', // Map to approver_name
          createdDate: request.created_date || 'N/A',
          approvedDate: request.approved_date || 'N/A',
        }));
      })
      .catch((error) => {
        $log.error('Error fetching requests:', error);
        $scope.errorMessage = 'Error fetching requests. Please try again later.';
      })
      .finally(() => {
        $scope.loading = false;
      });
  }

  // Set the active tab
  $scope.setActiveTab = function setActiveTab(tab) {
    $scope.activeTab = tab;
    if (tab === 'approvals') {
      fetchApprovals();
    } else if (tab === 'requests') {
      fetchRequests();
    }
  };

  // Toggle selection for individual approvals
  $scope.toggleSelection = function toggleSelection(approvalId) {
    $log.debug('Toggling selection for approval ID:', approvalId);

    const selectedApproval = $scope.approvals.find(a => a.approval_id === approvalId);

    if (selectedApproval) {
      selectedApproval.selected = !selectedApproval.selected;
      $log.debug('Approval selection toggled:', selectedApproval);
    } else {
      $log.error('Approval not found for ID:', approvalId);
    }

    // Update the "Select All" checkbox state
    $scope.selectAllChecked = $scope.approvals.every(a => a.selected);
  };

  // Toggle "Select All" checkbox
  $scope.toggleSelectAll = function toggleSelectAll() {
    $scope.selectAllChecked = !$scope.selectAllChecked;

    $scope.approvals.forEach((approval) => {
      approval.selected = $scope.selectAllChecked;
    });

    $log.debug('Toggled Select All:', $scope.selectAllChecked);
  };

  // Check if any approval is selected
  $scope.hasSelectedApprovals = function hasSelectedApprovals() {
    return $scope.approvals.some(approval => approval.selected);
  };

  // Approve selected approvals
  $scope.approveSelected = function approveSelected() {
    const selectedApprovals = $scope.approvals.filter(approval => approval.selected);

    if (selectedApprovals.length === 0) {
      $log.warn('No approvals selected for approval.');
      return;
    }

    const orgSlug = window.location.pathname.split('/')[1] || 'default';
    const apiUrl = `/${orgSlug}/api/approvals`;

    $log.debug('Approving selected approvals:', selectedApprovals);

    const requests = selectedApprovals.map((approval) => {
      if (!approval.approval_id) {
        $log.error('Approval ID is undefined:', approval);
        return Promise.reject(new Error('Approval ID is undefined'));
      }

      return $http.post(`${apiUrl}/${approval.approval_id}/update`, { status: 'Approved' });
    });

    Promise.all(requests)
      .then(() => {
        $log.debug('Approved successfully.');
        fetchApprovals();
        showPopupMessage('Approved successfully.');
      })
      .catch((error) => {
        $log.error('Error approving selected approvals:', error);
        $scope.errorMessage = 'Error approving selected approvals. Please try again later.';
      });
  };

  // Decline selected approvals
  $scope.declineSelected = function declineSelected() {
    const selectedApprovals = $scope.approvals.filter(approval => approval.selected);

    if (selectedApprovals.length === 0) {
      $log.warn('No approvals selected for decline.');
      return;
    }

    const orgSlug = window.location.pathname.split('/')[1] || 'default';
    const apiUrl = `/${orgSlug}/api/approvals`;

    $log.debug('Declining selected approvals:', selectedApprovals);

    const requests = selectedApprovals.map((approval) => {
      if (!approval.approval_id) {
        $log.error('Approval ID is undefined:', approval);
        return Promise.reject(new Error('Approval ID is undefined'));
      }

      return $http.post(`${apiUrl}/${approval.approval_id}/update`, { status: 'Declined' });
    });

    Promise.all(requests)
      .then(() => {
        $log.debug('Selected approvals declined successfully.');
        fetchApprovals();
        showPopupMessage('Selected approvals declined successfully.');
      })
      .catch((error) => {
        $log.error('Error declining selected approvals:', error);
        $scope.errorMessage = 'Error declining selected approvals. Please try again later.';
      });
  };

  // Fetch initial data
  fetchApprovals();
}

const ngModule = angular.module('app');
ngModule.controller('MyApprovalsController', MyApprovalsController);

ngModule.component('myApprovals', {
  template: `
    <div>
      <h2>My Approvals</h2>
      <div class="ui success message" ng-if="successMessage">
        <i class="close icon" ng-click="successMessage = ''"></i>
        <div class="header">{{ successMessage }}</div>
      </div>
      <div class="ui top attached tabular menu">
        <a
          class="item"
          ng-class="{active: activeTab === 'approvals'}"
          ng-click="setActiveTab('approvals')">
          Approvals
        </a>
        <a
          class="item"
          ng-class="{active: activeTab === 'requests'}"
          ng-click="setActiveTab('requests')">
          Requests
        </a>
      </div>
      <div class="ui bottom attached segment" ng-if="loading">Loading...</div>
      <div class="ui bottom attached segment" ng-if="errorMessage">{{ errorMessage }}</div>

      <!-- Approvals Table -->
      <div class="ui bottom attached segment" ng-if="!loading && activeTab === 'approvals'">
        <button
          class="ui green button"
          ng-click="approveSelected()"
          ng-disabled="!hasSelectedApprovals()">
          Approve
        </button>
        <button
          class="ui red button"
          ng-click="declineSelected()"
          ng-disabled="!hasSelectedApprovals()">
          Decline
        </button>
        <table class="ui celled table">
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  ng-checked="selectAllChecked"
                  ng-click="toggleSelectAll()" />
              </th>
              <th>Type</th>
              <th>Requester</th>
              <th>Project/Group Name</th>
              <th>Data Source Name</th>
              <th>Status</th>
              <th>Comments</th>
            </tr>
          </thead>
          <tbody>
            <tr ng-repeat="approval in approvals">
              <td>
                <input
                  type="checkbox"
                  ng-checked="approval.selected"
                  ng-click="toggleSelection(approval.approval_id)" />
              </td>
              <td>{{ approval.type }}</td>
              <td>{{ approval.requester }}</td>
              <td>{{ approval.projectOrGroupName }}</td>
              <td>{{ approval.data_source_name || 'N/A' }}</td>
              <td>{{ approval.status }}</td>
              <td>{{ approval.comments || 'N/A' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Requests Table -->
      <div class="ui bottom attached segment" ng-if="!loading && activeTab === 'requests'">
        <table class="ui celled table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Owner</th>
              <th>Project/Group Name</th>
              <th>Data Source Name</th>
              <th>Created Date</th>
              <th>Approved Date</th>
              <th>Status</th>
              <th>Comments</th>
            </tr>
          </thead>
          <tbody>
            <tr ng-repeat="request in requests">
              <td>{{ request.type }}</td>
              <td>{{ request.owner }}</td>
              <td>{{ request.projectOrGroupName }}</td>
              <td>{{ request.data_source_name || 'N/A' }}</td>
              <td>{{ request.createdDate }}</td>
              <td>{{ request.approvedDate }}</td>
              <td>{{ request.status }}</td>
              <td>{{ request.comments || 'N/A' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  controller: 'MyApprovalsController',
});

settingsMenu.add({
  permission: 'admin',
  title: 'My Approvals',
  path: 'my_approvals',
  order: 4,
});

ngModule.config([
  '$routeProvider',
  function configureRoutes($routeProvider) {
    $routeProvider.when('/my_approvals', {
      template: `
        <div>
          <app-header></app-header> <!-- Ensures the top header is rendered -->
          <settings-screen> <!-- Ensures the settings layout and side menu -->
            <my-approvals></my-approvals>
          </settings-screen>
        </div>
      `,
      controller($scope, $exceptionHandler) {
        'ngInject';

        $scope.handleError = $exceptionHandler;
      },
    });
  },
]);
