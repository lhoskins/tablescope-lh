import React from 'react';
import PropTypes from 'prop-types';
import { react2angular } from 'react2angular';
import Button from 'antd/lib/button';
import Card from 'antd/lib/card';
import Input from 'antd/lib/input';
import Modal from 'antd/lib/modal';
import Table from 'antd/lib/table';
import Tag from 'antd/lib/tag';
import Tooltip from 'antd/lib/tooltip';
import Alert from 'antd/lib/alert';
import Spin from 'antd/lib/spin';

import { $http } from '@/services/ng';
import recordEvent from '@/services/recordEvent';
import notification from '@/services/notification';
import { routesToAngularRoutes } from '@/lib/utils';
import PermissionGuard from '@/components/PermissionGuard';
import { currentUser } from '@/services/auth';
import navigateTo from '@/services/navigateTo';

class VDBManagement extends React.Component {
  static propTypes = {
    onError: PropTypes.func,
  };

  static defaultProps = {
    onError: () => {},
  };

  formRef = React.createRef();

  state = {
    organizations: [],
    loading: false,
    createModalVisible: false,
    confirmModalVisible: false,
    rotateModalVisible: false,
    selectedOrg: null,
    formValues: {},
    provisioningData: null,
  };

  componentDidMount() {
    console.log('[VDBManagement] Component mounted');
    
    // Check if user has super_admin permission
    if (!currentUser.hasPermission || !currentUser.hasPermission('super_admin')) {
      notification.error('Access denied. Super Admin permission required.');
      navigateTo('/', true);
      return;
    }
    
    recordEvent('view', 'page', 'admin/vdb-management');
    console.log('[VDBManagement] Calling loadOrganizations');
    this.loadOrganizations();
  }

  loadOrganizations = async () => {
    console.log('[VDBManagement] loadOrganizations called');
    this.setState({ loading: true });
    try {
      // Get org slug from URL (e.g., /production/admin/vdb-management)
      const orgSlug = window.location.pathname.split('/')[1] || 'default';
      console.log('[VDBManagement] Org slug from URL:', orgSlug);
      
      // Get current organization from session API
      let orgId = null;
      let orgName = null;
      
      try {
        // Get current organization from session API (now includes org_id and org_name)
        const sessionResponse = await $http.get('api/session');
        console.log('[VDBManagement] Session response:', sessionResponse.data);
        
        if (sessionResponse.data && sessionResponse.data.org_id) {
          orgId = sessionResponse.data.org_id;
          orgName = sessionResponse.data.org_name || orgSlug.charAt(0).toUpperCase() + orgSlug.slice(1);
          console.log('[VDBManagement] Got org from session:', orgId, orgName);
        } else {
          console.error('[VDBManagement] Session data:', JSON.stringify(sessionResponse.data));
          throw new Error('No org_id in session response');
        }
      } catch (sessionError) {
        console.error('[VDBManagement] Could not get org from session:', sessionError);
        notification.error('Failed to get current organization from session. Please refresh the page.');
        this.setState({ loading: false });
        return;
      }
      
      if (!orgId) {
        console.error('[VDBManagement] No organization ID available');
        notification.error('No organization ID available. Please ensure you are logged in.');
        this.setState({ loading: false });
        return;
      }
      
      const org = {
        id: orgId,
        name: orgName,
        slug: orgSlug,
        hasVDB: false,
        vdb: null,
      };
      
      console.log('[VDBManagement] Created org object:', org);
      
      // Fetch VDB status for the organization
      try {
        console.log('[VDBManagement] Fetching VDB status for org:', orgId);
        const vdbResponse = await $http.get(`api/organizations/${org.id}/vdb`);
        console.log('[VDBManagement] VDB response:', vdbResponse);
        org.vdb = vdbResponse.data;
        org.hasVDB = true;
      } catch (error) {
        // VDB not provisioned yet (404 is expected)
        console.log('[VDBManagement] No VDB found (expected):', error.status);
        org.vdb = null;
        org.hasVDB = false;
      }
      
      console.log('[VDBManagement] Setting organizations state:', [org]);
      this.setState({ organizations: [org] });
      console.log('[VDBManagement] Organizations state set successfully');
    } catch (error) {
      console.error('[VDBManagement] Error loading organizations:', error);
      notification.error('Failed to load organization: ' + (error.message || 'Unknown error'));
      this.props.onError(error);
    } finally {
      this.setState({ loading: false });
      console.log('[VDBManagement] Loading complete');
    }
  };

  handlePrepareProvisioning = async (values) => {
    console.log('Prepare provisioning clicked, values:', values);
    this.setState({ loading: true });
    try {
      // Generate VDB ID on the frontend (7-digit random number)
      const vdbId = String(Math.floor(1000000 + Math.random() * 9000000));
      
      // Get organization details
      const org = this.state.organizations.find(o => o.id === values.organizationId);
      
      // Prepare provisioning data
      const provisioningData = {
        organizationId: values.organizationId,
        organizationName: org.name,
        organizationSlug: org.slug,
        vdbId: vdbId,
        vdbHost: 'localhost', // Will be set by backend
        vdbPort: 31020, // Will be set by backend
        customerFolder: `/opt/wildfly/teiidfiles/customers/${values.organizationId}`,
        uploadsFolder: `/opt/wildfly/teiidfiles/customers/${values.organizationId}/uploads`,
      };
      
      console.log('Provisioning data prepared:', provisioningData);
      
      // Show confirmation modal
      this.setState({ 
        createModalVisible: false,
        confirmModalVisible: true,
        provisioningData: provisioningData,
      });
    } catch (error) {
      console.error('Failed to prepare provisioning:', error);
      notification.error('Failed to prepare provisioning: ' + (error.message || 'Unknown error'));
      this.props.onError(error);
    } finally {
      this.setState({ loading: false });
    }
  };

  handleConfirmProvisioning = async () => {
    console.log('Confirm provisioning clicked');
    const { provisioningData } = this.state;
    
    if (!provisioningData) {
      notification.error('No provisioning data available');
      return;
    }
    
    this.setState({ loading: true });
    try {
      console.log('Making POST request to:', `api/organizations/${provisioningData.organizationId}/vdb`);
      const response = await $http.post(`api/organizations/${provisioningData.organizationId}/vdb`, {
        provision: true,
      });
      console.log('VDB provisioned successfully:', response);
      
      notification.success('VDB provisioned successfully');
      this.setState({ 
        confirmModalVisible: false, 
        provisioningData: null,
        formValues: {} 
      });
      if (this.formRef.current) {
        this.formRef.current.resetFields();
      }
      this.loadOrganizations();
    } catch (error) {
      console.error('Failed to provision VDB:', error);
      const errorMessage = error.data?.message || error.message || error.statusText || 'Unknown error occurred';
      notification.error('Failed to provision VDB: ' + errorMessage);
      this.props.onError(error);
    } finally {
      this.setState({ loading: false });
    }
  };

  handleReprovisionVDB = (orgId, orgName) => {
    Modal.confirm({
      title: 'Re-Provision VDB',
      content: (
        <div>
          <p>Re-provision the VDB for organization "{orgName}" with customer-specific paths?</p>
          <p style={{ marginTop: 10, padding: 10, background: '#f0f0f0', borderRadius: 4 }}>
            This will:
            <ul style={{ marginTop: 8, marginBottom: 0 }}>
              <li>Delete the existing VDB</li>
              <li>Create a new VDB with customer-specific folder paths</li>
              <li>Update file references to use /opt/wildfly/teiidfiles/customers/{orgId}/uploads/</li>
            </ul>
          </p>
        </div>
      ),
      okText: 'Re-Provision',
      okType: 'primary',
      onOk: async () => {
        this.setState({ loading: true });
        try {
          // Call API with force=true to re-provision
          await $http.post(`api/organizations/${orgId}/vdb`, { force: true });
          notification.success('VDB re-provisioned successfully with customer-specific paths');
          this.loadOrganizations();
        } catch (error) {
          console.error('Failed to re-provision VDB:', error);
          const errorMessage = error.data?.message || error.message || error.statusText || 'Unknown error occurred';
          notification.error('Failed to re-provision VDB: ' + errorMessage);
          this.props.onError(error);
        } finally {
          this.setState({ loading: false });
        }
      },
    });
  };

  handleDeleteVDB = (orgId, orgName) => {
    Modal.confirm({
      title: 'Delete VDB',
      content: `Are you sure you want to delete the VDB for organization "${orgName}"? This action cannot be undone.`,
      okText: 'Delete',
      okType: 'danger',
      onOk: async () => {
        this.setState({ loading: true });
        try {
          await $http.delete(`api/organizations/${orgId}/vdb`);
          notification.success('VDB deleted successfully');
          this.loadOrganizations();
        } catch (error) {
          console.error('Failed to delete VDB:', error);
          const errorMessage = error.data?.message || error.message || error.statusText || 'Unknown error occurred';
          notification.error('Failed to delete VDB: ' + errorMessage);
          this.props.onError(error);
        } finally {
          this.setState({ loading: false });
        }
      },
    });
  };

  handleRotateCredentials = async () => {
    this.setState({ loading: true });
    try {
      await $http.post(`api/organizations/${this.state.selectedOrg.id}/vdb/rotate-credentials`);
      notification.success('VDB credentials rotated successfully');
      this.setState({ rotateModalVisible: false, selectedOrg: null });
      this.loadOrganizations();
    } catch (error) {
      notification.error('Failed to rotate credentials: ' + (error.data?.message || error.message));
      this.props.onError(error);
    } finally {
      this.setState({ loading: false });
    }
  };

  handleCheckHealth = async (orgId) => {
    this.setState({ loading: true });
    try {
      const { data } = await $http.get(`api/organizations/${orgId}/vdb/health`);
      
      if (data.status === 'healthy') {
        notification.success(`VDB is healthy (${data.response_time}ms)`);
      } else {
        notification.warning(`VDB status: ${data.status}`);
      }
      
      this.loadOrganizations();
    } catch (error) {
      notification.error('Failed to check VDB health: ' + (error.data?.message || error.message));
      this.props.onError(error);
    } finally {
      this.setState({ loading: false });
    }
  };

  getColumns = () => {
    console.log('[VDBManagement] getColumns called');
    
    const columns = [
      {
        title: 'Organization',
        dataIndex: 'name',
        key: 'name',
        render: (text, record) => (
          <div>
            <div style={{ fontWeight: 500 }}>{text}</div>
            <div style={{ fontSize: '12px', color: '#888' }}>Slug: {record.slug}</div>
          </div>
        ),
      },
      {
        title: 'VDB Status',
        key: 'vdb_status',
        render: (_, record) => {
          if (!record.hasVDB) {
            return <Tag color="default">No VDB</Tag>;
          }
          
          if (!record.vdb.is_active) {
            return <Tag color="red">✗ Inactive</Tag>;
          }
          
          const healthStatus = record.vdb.health_status || 'unknown';
          const statusColors = {
            healthy: 'green',
            degraded: 'orange',
            down: 'red',
            unknown: 'default',
          };
          
          const statusSymbols = {
            healthy: '✓',
            degraded: '⟳',
            down: '✗',
            unknown: '?',
          };
          
          return (
            <Tag color={statusColors[healthStatus]}>
              {statusSymbols[healthStatus]} {healthStatus.toUpperCase()}
            </Tag>
          );
        },
      },
      {
        title: 'VDB ID',
        dataIndex: ['vdb', 'vdb_id'],
        key: 'vdb_id',
        render: (text) => text || '-',
      },
      {
        title: 'Host:Port',
        key: 'connection',
        render: (_, record) => {
          if (!record.hasVDB) return '-';
          return `${record.vdb.vdb_host}:${record.vdb.vdb_port}`;
        },
      },
      {
        title: 'Last Health Check',
        dataIndex: ['vdb', 'last_health_check'],
        key: 'last_health_check',
        render: (text) => {
          if (!text) return '-';
          const date = new Date(text);
          return (
            <Tooltip title={date.toLocaleString()}>
              {date.toLocaleDateString()}
            </Tooltip>
          );
        },
      },
      {
        title: 'Actions',
        key: 'actions',
        render: (_, record) => (
          <div style={{ display: 'inline-flex', gap: '8px' }}>
            {!record.hasVDB ? (
              <Button
                type="primary"
                size="small"
                onClick={() => {
                  this.setState({ 
                    formValues: { organizationId: record.id },
                    createModalVisible: true 
                  }, () => {
                    // Set form values after modal opens
                    if (this.formRef.current) {
                      this.formRef.current.setFieldsValue({ organizationId: record.id });
                    }
                  });
                }}
              >
                + Provision VDB
              </Button>
            ) : (
              <>
                <Tooltip title="Check Health">
                  <Button
                    size="small"
                    onClick={() => this.handleCheckHealth(record.id)}
                  >
                    ⟳
                  </Button>
                </Tooltip>
                <Tooltip title="Re-Provision with Customer Paths">
                  <Button
                    size="small"
                    type="primary"
                    onClick={() => this.handleReprovisionVDB(record.id, record.name)}
                  >
                    🔄
                  </Button>
                </Tooltip>
                <Tooltip title="Rotate Credentials">
                  <Button
                    size="small"
                    onClick={() => {
                      this.setState({
                        selectedOrg: record,
                        rotateModalVisible: true
                      });
                    }}
                  >
                    🔑
                  </Button>
                </Tooltip>
                <Tooltip title="Delete VDB">
                  <Button
                    size="small"
                    danger
                    onClick={() => this.handleDeleteVDB(record.id, record.name)}
                  >
                    ✗
                  </Button>
                </Tooltip>
              </>
            )}
          </div>
        ),
      },
    ];
    
    console.log('[VDBManagement] getColumns returning', columns.length, 'columns');
    return columns;
  };

  render() {
    const { organizations, loading, createModalVisible, confirmModalVisible, rotateModalVisible, selectedOrg, formValues, provisioningData } = this.state;
    
    console.log('[VDBManagement] Rendering with organizations:', organizations);
    console.log('[VDBManagement] Loading:', loading);
    console.log('[VDBManagement] Organizations length:', organizations.length);
    
    // Debug: Check if we have data
    if (organizations.length > 0) {
      console.log('[VDBManagement] First org:', organizations[0]);
    }

    // CRITICAL DEBUG: Test if render is even being called
    console.log('[VDBManagement] RENDER METHOD EXECUTING');

    return (
      <PermissionGuard permission="super_admin">
        <div className="container">
        <div className="page-header">
          <h3>VDB Multi-Tenancy Management</h3>
        </div>
        
        <div className="vdb-management-page" style={{ padding: '20px' }}>
          {/* CRITICAL: Visible debug box */}
          <div style={{ 
            marginBottom: 20, 
            padding: 20, 
            background: '#ffeb3b', 
            border: '3px solid #f44336',
            fontSize: 16,
            fontWeight: 'bold'
          }}>
            🔍 DEBUG: Component is rendering!
            <br />
            Organizations loaded: {organizations.length}
            <br />
            {organizations.length > 0 && (
              <>
                First org: {organizations[0].name} (ID: {organizations[0].id})
                <br />
                Has VDB: {organizations[0].hasVDB ? 'YES' : 'NO'}
              </>
            )}
          </div>

          <Card
            title="VDB Multi-Tenancy Management"
            extra={
              <Button
                onClick={this.loadOrganizations}
                loading={loading}
              >
                ⟳ Refresh
              </Button>
            }
          >
            <Alert
              message="VDB Multi-Tenancy"
              description="Manage Virtual Database (VDB) instances for organization-level data isolation. Each organization can have its own VDB with unique credentials."
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            <Spin spinning={loading}>
              <Table
                columns={this.getColumns()}
                dataSource={organizations}
                rowKey="id"
                pagination={{ pageSize: 10 }}
                locale={{ emptyText: 'No organizations found' }}
              />
            </Spin>
          </Card>

          {/* Create VDB Modal */}
          <Modal
            title="Provision VDB"
            visible={createModalVisible}
            onCancel={() => {
              this.setState({ createModalVisible: false, formValues: {} });
            }}
            onOk={() => {
              console.log('Modal OK clicked, formValues:', formValues);
              this.handlePrepareProvisioning(formValues);
            }}
            okText="Next: Review"
            okButtonProps={{ loading }}
          >
            <Alert
              message="VDB Provisioning"
              description="This will create a new VDB instance from the template, generate secure credentials, and deploy it to the Teiid server."
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            <div style={{ marginTop: 16 }}>
              <label style={{ display: 'block', marginBottom: 8, fontWeight: 500 }}>
                Organization ID
              </label>
              <Input 
                disabled 
                value={formValues.organizationId} 
                style={{ width: '100%' }}
              />
            </div>
          </Modal>

          {/* Confirmation Modal */}
          <Modal
            title="Confirm VDB Provisioning"
            visible={this.state.confirmModalVisible}
            onCancel={() => {
              this.setState({ confirmModalVisible: false, provisioningData: null });
            }}
            onOk={this.handleConfirmProvisioning}
            okText="Provision VDB"
            okButtonProps={{ loading, type: 'primary' }}
            width={600}
          >
            <Alert
              message="Review VDB Configuration"
              description="Please review the VDB configuration before provisioning. This information will be used to create the VDB instance."
              type="info"
              showIcon
              style={{ marginBottom: 20 }}
            />

            {this.state.provisioningData && (
              <div style={{ 
                background: '#f5f5f5', 
                padding: 20, 
                borderRadius: 4,
                fontFamily: 'monospace'
              }}>
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontWeight: 'bold', marginBottom: 8, color: '#1890ff' }}>
                    Organization Details
                  </div>
                  <div style={{ paddingLeft: 16 }}>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>ID:</span>{' '}
                      <span style={{ fontWeight: 'bold' }}>{this.state.provisioningData.organizationId}</span>
                    </div>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>Name:</span>{' '}
                      <span style={{ fontWeight: 'bold' }}>{this.state.provisioningData.organizationName}</span>
                    </div>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>Slug:</span>{' '}
                      <span style={{ fontWeight: 'bold' }}>{this.state.provisioningData.organizationSlug}</span>
                    </div>
                  </div>
                </div>

                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontWeight: 'bold', marginBottom: 8, color: '#52c41a' }}>
                    VDB Configuration
                  </div>
                  <div style={{ paddingLeft: 16 }}>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>VDB ID:</span>{' '}
                      <span style={{ 
                        fontWeight: 'bold', 
                        fontSize: 16,
                        color: '#52c41a',
                        background: '#fff',
                        padding: '2px 8px',
                        borderRadius: 3
                      }}>
                        {this.state.provisioningData.vdbId}
                      </span>
                    </div>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>Host:</span>{' '}
                      <span>{this.state.provisioningData.vdbHost}</span>
                    </div>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>Port:</span>{' '}
                      <span>{this.state.provisioningData.vdbPort}</span>
                    </div>
                  </div>
                </div>

                <div>
                  <div style={{ fontWeight: 'bold', marginBottom: 8, color: '#fa8c16' }}>
                    Customer Folders
                  </div>
                  <div style={{ paddingLeft: 16 }}>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>VDB Folder:</span>{' '}
                      <span style={{ fontSize: 12 }}>{this.state.provisioningData.customerFolder}</span>
                    </div>
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: '#666' }}>Uploads Folder:</span>{' '}
                      <span style={{ fontSize: 12 }}>{this.state.provisioningData.uploadsFolder}</span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            <Alert
              message="Note"
              description="Secure credentials will be automatically generated during provisioning. The VDB will be deployed to the Teiid server and ready for use."
              type="warning"
              showIcon
              style={{ marginTop: 20 }}
            />
          </Modal>

          {/* Rotate Credentials Modal */}
          <Modal
            title="Rotate VDB Credentials"
            visible={rotateModalVisible}
            onCancel={() => {
              this.setState({ rotateModalVisible: false, selectedOrg: null });
            }}
            onOk={this.handleRotateCredentials}
            okText="Rotate Credentials"
            okButtonProps={{ danger: true, loading }}
          >
            <Alert
              message="Security Warning"
              description={
                <>
                  <p>This will generate new credentials for the VDB and update the Teiid configuration.</p>
                  <p><strong>Existing connections will be invalidated.</strong></p>
                  {selectedOrg && (
                    <p>Organization: <strong>{selectedOrg.name}</strong></p>
                  )}
                </>
              }
              type="warning"
              showIcon
            />
          </Modal>
        </div>
      </div>
      </PermissionGuard>
    );
  }
}

export default function init(ngModule) {
  ngModule.component('pageVdbManagement', react2angular(VDBManagement));

  return routesToAngularRoutes([
    {
      path: '/admin/vdb-management',
      title: 'VDB Management',
      key: 'vdb_management',
    },
  ], {
    template: '<page-vdb-management on-error="handleError"></page-vdb-management>',
    controller($scope, $exceptionHandler) {
      'ngInject';

      $scope.handleError = $exceptionHandler;
    },
  });
}

init.init = true;
