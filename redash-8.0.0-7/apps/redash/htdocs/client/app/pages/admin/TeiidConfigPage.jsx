import React from 'react';
import PropTypes from 'prop-types';
import { react2angular } from 'react2angular';
import { routesToAngularRoutes } from '@/lib/utils';
import recordEvent from '@/services/recordEvent';
import notification from '@/services/notification';
import Layout from '@/components/admin/Layout';

console.log('[TeiidConfigPage] Module loaded');

const getOrgSlug = () => window.location.pathname.split('/')[1] || '';
const apiBase = getOrgSlug() ? `/${getOrgSlug()}/api` : '/api';
console.log('[TeiidConfigPage] API base:', apiBase);

class TeiidConfigPage extends React.Component {
  static propTypes = {
    onError: PropTypes.func,
  };

  static defaultProps = {
    onError: () => {},
  };

  state = {
    loading: true,
    saving: false,
    testing: false,
    configured: false,
    config: {
      servlet_url: 'http://localhost:8095/TeiidExcelImporterTest/vdb-management',
      servlet_api_key: '',
      teiid_host: 'localhost',
      teiid_port: 31020,
      teiid_use_ssl: true,
      customer_base_path: '/opt/wildfly/teiidfiles/customers',
      vdb_base_path: '/opt/wildfly/teiidfiles',
      template_vdb_name: 'MyVDBTest',
      vdb_enabled: true,
    },
    message: null,
    testResult: null,
  };

  componentDidMount() {
    console.log('[TeiidConfigPage] Component mounted, loading config...');
    recordEvent('view', 'page', 'admin/teiid_config');
    this.loadConfig();
  }

  loadConfig = () => {
    const url = `${apiBase}/admin/teiid-config`;
    console.log('[TeiidConfigPage] Fetching config from:', url);
    
    fetch(url, {
      credentials: 'same-origin',
    })
      .then(response => {
        console.log('[TeiidConfigPage] Response status:', response.status);
        if (!response.ok) {
          throw new Error(`Failed to load configuration (status: ${response.status})`);
        }
        return response.json();
      })
      .then(data => {
        console.log('[TeiidConfigPage] Config data received:', data);
        if (data.configured) {
          this.setState({
            configured: true,
            config: {
              servlet_url: data.servlet_url || this.state.config.servlet_url,
              servlet_api_key: '',
              teiid_host: data.teiid_host || this.state.config.teiid_host,
              teiid_port: data.teiid_port || this.state.config.teiid_port,
              teiid_use_ssl: data.teiid_use_ssl !== undefined ? data.teiid_use_ssl : this.state.config.teiid_use_ssl,
              customer_base_path: data.customer_base_path || this.state.config.customer_base_path,
              vdb_base_path: data.vdb_base_path || this.state.config.vdb_base_path,
              template_vdb_name: data.template_vdb_name || this.state.config.template_vdb_name,
              vdb_enabled: data.vdb_enabled !== undefined ? data.vdb_enabled : this.state.config.vdb_enabled,
            },
            message: { type: 'info', text: 'Configuration loaded. API key is hidden for security.' },
            loading: false,
          });
        } else if (data.defaults) {
          console.log('[TeiidConfigPage] Using default config');
          this.setState({
            config: { ...this.state.config, ...data.defaults },
            message: { type: 'warning', text: 'Teiid not configured yet. Please enter your configuration below.' },
            loading: false,
          });
        } else {
          console.log('[TeiidConfigPage] No config data, setting loading to false');
          this.setState({ loading: false });
        }
      })
      .catch(error => {
        console.error('[TeiidConfigPage] Error loading config:', error);
        this.setState({
          message: { type: 'error', text: `Failed to load configuration: ${error.message}` },
          loading: false,
        });
      });
  };

  handleChange = (field, value) => {
    this.setState({
      config: { ...this.state.config, [field]: value },
      message: null,
      testResult: null,
    });
  };

  handleTestConnection = () => {
    const { config } = this.state;
    
    if (!config.servlet_url || !config.servlet_api_key) {
      this.setState({
        testResult: { type: 'error', text: 'Please enter Servlet URL and API Key before testing.' },
      });
      return;
    }

    this.setState({ testing: true, testResult: null });

    fetch(`${apiBase}/admin/teiid-config/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        servlet_url: config.servlet_url,
        servlet_api_key: config.servlet_api_key,
      }),
    })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          this.setState({
            testResult: { type: 'success', text: '✓ Connection successful! Teiid servlet is accessible.' },
            testing: false,
          });
        } else {
          this.setState({
            testResult: { type: 'error', text: `✗ Connection failed: ${data.message}` },
            testing: false,
          });
        }
      })
      .catch(error => {
        this.setState({
          testResult: { type: 'error', text: `✗ Connection test failed: ${error.message}` },
          testing: false,
        });
      });
  };

  handleSave = () => {
    const { config } = this.state;

    if (!config.servlet_url || !config.servlet_api_key || !config.customer_base_path) {
      this.setState({
        message: { type: 'error', text: 'Please fill in all required fields (Servlet URL, API Key, Customer Base Path).' },
      });
      return;
    }

    this.setState({ saving: true, message: null });

    fetch(`${apiBase}/admin/teiid-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(config),
    })
      .then(response => {
        if (!response.ok) {
          return response.json().then(data => {
            throw new Error(data.error || 'Failed to save configuration');
          });
        }
        return response.json();
      })
      .then(data => {
        this.setState({
          configured: true,
          message: { type: 'success', text: `✓ ${data.message}` },
          saving: false,
        });
        notification.success(data.message);
        setTimeout(() => this.loadConfig(), 1000);
      })
      .catch(error => {
        this.setState({
          message: { type: 'error', text: `Failed to save configuration: ${error.message}` },
          saving: false,
        });
        notification.error(`Failed to save configuration: ${error.message}`);
      });
  };

  renderMessage(msg) {
    if (!msg) return null;
    
    const colors = {
      success: '#4caf50',
      error: '#f44336',
      warning: '#ff9800',
      info: '#2196f3',
    };

    return (
      <div style={{
        padding: '12px 16px',
        marginBottom: '16px',
        borderRadius: '4px',
        backgroundColor: colors[msg.type] || colors.info,
        color: '#fff',
      }}>
        {msg.text}
      </div>
    );
  }

  render() {
    const { loading, saving, testing, configured, config, message, testResult } = this.state;
    console.log('[TeiidConfigPage] Rendering, loading:', loading);

    if (loading) {
      return (
        <Layout activeTab="teiid_config">
          <div style={{ textAlign: 'center', padding: '40px' }}>
            <div>Loading configuration...</div>
          </div>
        </Layout>
      );
    }

    return (
      <Layout activeTab="teiid_config">
        <div className="container" style={{ maxWidth: '800px', margin: '0 auto', padding: '20px' }}>
          <h3>Teiid Environment Configuration</h3>
          <p style={{ color: '#666', marginBottom: '20px' }}>
            One-time setup for Teiid servlet and customer folder paths. This configuration is stored
            in the database and used by all file upload operations.
          </p>

          {this.renderMessage(message)}

          {/* Teiid Servlet Configuration */}
          <div style={{ marginTop: '30px' }}>
            <h4>Teiid Servlet Configuration</h4>
            <hr />
            
            <div className="form-group">
              <label>Servlet URL *</label>
              <input
                type="text"
                className="form-control"
                value={config.servlet_url}
                onChange={(e) => this.handleChange('servlet_url', e.target.value)}
                placeholder="http://localhost:8095/TeiidExcelImporterTest/vdb-management"
              />
              <small className="form-text text-muted">Full URL to the Teiid VDB management servlet</small>
            </div>

            <div className="form-group">
              <label>Servlet API Key *</label>
              <input
                type="password"
                className="form-control"
                value={config.servlet_api_key}
                onChange={(e) => this.handleChange('servlet_api_key', e.target.value)}
                placeholder="Enter API key for servlet authentication"
              />
              <small className="form-text text-muted">
                {configured ? 'Leave blank to keep existing key' : 'API key for authenticating to the servlet'}
              </small>
            </div>
          </div>

          {/* Teiid Server Configuration */}
          <div style={{ marginTop: '30px' }}>
            <h4>Teiid Server Configuration</h4>
            <hr />
            
            <div className="row">
              <div className="col-md-8">
                <div className="form-group">
                  <label>Teiid Host</label>
                  <input
                    type="text"
                    className="form-control"
                    value={config.teiid_host}
                    onChange={(e) => this.handleChange('teiid_host', e.target.value)}
                    placeholder="localhost"
                  />
                </div>
              </div>
              <div className="col-md-4">
                <div className="form-group">
                  <label>Teiid Port</label>
                  <input
                    type="number"
                    className="form-control"
                    value={config.teiid_port}
                    onChange={(e) => this.handleChange('teiid_port', parseInt(e.target.value, 10))}
                    placeholder="31020"
                  />
                </div>
              </div>
            </div>

            <div className="form-group">
              <div className="checkbox">
                <label>
                  <input
                    type="checkbox"
                    checked={config.teiid_use_ssl}
                    onChange={(e) => this.handleChange('teiid_use_ssl', e.target.checked)}
                  />
                  {' '}Use SSL for Teiid connections
                </label>
              </div>
            </div>
          </div>

          {/* File System Configuration */}
          <div style={{ marginTop: '30px' }}>
            <h4>File System Configuration</h4>
            <hr />
            
            <div className="form-group">
              <label>Customer Base Path *</label>
              <input
                type="text"
                className="form-control"
                value={config.customer_base_path}
                onChange={(e) => this.handleChange('customer_base_path', e.target.value)}
                placeholder="/opt/wildfly/teiidfiles/customers"
              />
              <small className="form-text text-muted">
                Base directory for customer-specific folders (e.g., /customers/1/uploads/)
              </small>
            </div>

            <div className="form-group">
              <label>VDB Base Path</label>
              <input
                type="text"
                className="form-control"
                value={config.vdb_base_path}
                onChange={(e) => this.handleChange('vdb_base_path', e.target.value)}
                placeholder="/opt/wildfly/teiidfiles"
              />
              <small className="form-text text-muted">Base directory for VDB files and templates</small>
            </div>
          </div>

          {/* VDB Configuration */}
          <div style={{ marginTop: '30px' }}>
            <h4>VDB Configuration</h4>
            <hr />
            
            <div className="form-group">
              <label>Template VDB Name</label>
              <input
                type="text"
                className="form-control"
                value={config.template_vdb_name}
                onChange={(e) => this.handleChange('template_vdb_name', e.target.value)}
                placeholder="MyVDBTest"
              />
              <small className="form-text text-muted">
                Name of the template VDB to use for creating customer VDBs
              </small>
            </div>

            <div className="form-group">
              <div className="checkbox">
                <label>
                  <input
                    type="checkbox"
                    checked={config.vdb_enabled}
                    onChange={(e) => this.handleChange('vdb_enabled', e.target.checked)}
                  />
                  {' '}Enable VDB multi-tenancy
                </label>
              </div>
            </div>
          </div>

          {/* Test Result */}
          {testResult && this.renderMessage(testResult)}

          {/* Action Buttons */}
          <div style={{ marginTop: '30px', display: 'flex', gap: '10px' }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={this.handleSave}
              disabled={saving || testing}
            >
              {saving ? 'Saving...' : configured ? 'Update Configuration' : 'Save Configuration'}
            </button>

            <button
              type="button"
              className="btn btn-default"
              onClick={this.handleTestConnection}
              disabled={saving || testing}
              style={{ marginLeft: 'auto' }}
            >
              {testing ? 'Testing...' : 'Test Connection'}
            </button>
          </div>

          {/* Help Text */}
          <div style={{ marginTop: '20px', padding: '10px', backgroundColor: '#f5f5f5', borderRadius: '4px' }}>
            <small>
              <strong>Note:</strong> This configuration is stored in the database and applies to all organizations.
              Make sure the paths exist and have proper permissions before saving.
            </small>
          </div>
        </div>
      </Layout>
    );
  }
}

export default function init(ngModule) {
  ngModule.component('pageTeiidConfig', react2angular(TeiidConfigPage, ['onError']));

  return routesToAngularRoutes([
    {
      path: '/admin/teiid-config',
      title: 'Teiid Configuration',
      key: 'teiid_config',
    },
  ], {
    template: '<page-teiid-config on-error="handleError"></page-teiid-config>',
    controller($scope, $exceptionHandler) {
      'ngInject';
      $scope.handleError = $exceptionHandler;
    },
  });
}

init.init = true;
