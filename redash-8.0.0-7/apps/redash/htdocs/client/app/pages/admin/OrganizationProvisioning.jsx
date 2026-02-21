import React from 'react';
import PropTypes from 'prop-types';
import { react2angular } from 'react2angular';
import Button from 'antd/lib/button';
import Card from 'antd/lib/card';
import Form from 'antd/lib/form';
import Input from 'antd/lib/input';
import Alert from 'antd/lib/alert';
import Spin from 'antd/lib/spin';
import Steps from 'antd/lib/steps';
import Result from 'antd/lib/result';
import Divider from 'antd/lib/divider';
import { EditOutlined } from '@ant-design/icons';
import { debounce } from 'lodash';

import { $http } from '@/services/ng';
import recordEvent from '@/services/recordEvent';
import notification from '@/services/notification';
import { routesToAngularRoutes } from '@/lib/utils';

const { Step } = Steps;
const { TextArea } = Input;

class OrganizationProvisioning extends React.Component {
  static propTypes = {
    onError: PropTypes.func,
  };

  static defaultProps = {
    onError: () => {},
  };

  state = {
    loading: false,
    provisioning: false,
    provisioningComplete: false,
    provisioningError: null,
    currentStep: 0,
    showReview: false,
    isEditing: false,
    formValues: {
      organization_name: '',
      organization_email: '',
      address: '',  // Legacy field - will be auto-populated from structured fields
      contact_first_name: '',
      contact_last_name: '',
      contact_email: '',
      contact_phone: '',
      company_name: '',
      country: '',
      address_line1: '',
      address_line2: '',
      city: '',
      state_province: '',
      postal_code: '',
    },
    generatedSlug: '',
    slugAvailable: null,
    slugChecking: false,
    validationErrors: {},
    provisioningResult: null,
  };

  componentDidMount() {
    recordEvent('view', 'page', 'admin/organization-provisioning');
  }

  // Debounced slug generation and availability check
  checkSlugAvailability = debounce(async (slug) => {
    if (!slug || slug.length < 3) {
      this.setState({ slugAvailable: null });
      return;
    }

    this.setState({ slugChecking: true });
    try {
      const response = await $http.get(`api/admin/organizations/check-slug?slug=${encodeURIComponent(slug)}`);
      this.setState({
        slugAvailable: response.data.available,
        slugChecking: false,
      });
    } catch (error) {
      console.error('Failed to check slug availability:', error);
      this.setState({ 
        slugChecking: false,
        slugAvailable: null 
      });
      notification.warning('Could not verify slug availability. You can still proceed.');
    }
  }, 500);

  // Generate slug from organization name
  generateSlug = (name) => {
    if (!name) return '';
    
    const slug = name
      .toLowerCase()
      .trim()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-]/g, '')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
    
    return slug;
  };

  // Validation functions
  validateEmail = (email) => {
    const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    return emailPattern.test(email);
  };

  validateName = (name) => {
    const namePattern = /^[a-zA-Z\s\-']+$/;
    return name && name.trim() && namePattern.test(name) && name.length <= 100;
  };

  validateOrganizationName = (name) => {
    return name && name.trim() && name.length >= 3 && name.length <= 255;
  };

  // Handle form field changes
  handleFieldChange = (field, value) => {
    const newFormValues = {
      ...this.state.formValues,
      [field]: value,
    };

    this.setState({ formValues: newFormValues });

    // Auto-generate slug when organization name changes
    if (field === 'organization_name') {
      const slug = this.generateSlug(value);
      this.setState({ generatedSlug: slug });
      if (slug) {
        this.checkSlugAvailability(slug);
      }
    }

    // Validate field
    this.validateField(field, value);
  };

  validateField = (field, value) => {
    const errors = { ...this.state.validationErrors };

    switch (field) {
      case 'organization_name':
      case 'company_name':
        if (!this.validateOrganizationName(value)) {
          errors[field] = 'Name must be between 3 and 255 characters';
        } else {
          delete errors[field];
        }
        break;

      case 'contact_first_name':
      case 'contact_last_name':
        if (!this.validateName(value)) {
          errors[field] = 'Name can only contain letters, spaces, hyphens, and apostrophes';
        } else {
          delete errors[field];
        }
        break;

      case 'contact_email':
      case 'organization_email':
        if (!this.validateEmail(value)) {
          errors[field] = 'Invalid email format';
        } else {
          delete errors[field];
        }
        break;

      case 'address':
      case 'address_line1':
        // Address line 1 is required
        if (!value || !value.trim()) {
          errors[field] = 'Address is required';
        } else {
          delete errors[field];
        }
        break;

      case 'address_line2':
        // Address line 2 is optional, no validation needed
        delete errors[field];
        break;

      case 'city':
      case 'state_province':
      case 'postal_code':
      case 'country':
        // These fields are optional but should have reasonable length if provided
        if (value && value.trim() && value.length > 100) {
          errors[field] = 'Value is too long';
        } else {
          delete errors[field];
        }
        break;

      case 'contact_phone':
        // Phone is optional, but if provided should be valid
        if (value && value.trim() && !this.validatePhone(value)) {
          errors[field] = 'Invalid phone format';
        } else {
          delete errors[field];
        }
        break;

      default:
        break;
    }

    this.setState({ validationErrors: errors });
  };

  validatePhone = (phone) => {
    // Basic phone validation - allows various formats
    const phonePattern = /^[\d\s\-\+\(\)\.]+$/;
    return phone.length >= 10 && phone.length <= 20 && phonePattern.test(phone);
  };

  // Check if form is valid
  isFormValid = () => {
    const { formValues, validationErrors, slugAvailable } = this.state;

    // Required fields only
    const requiredFields = [
      'organization_name',
      'address_line1',
      'contact_first_name',
      'contact_last_name',
      'contact_email'
    ];

    const allRequiredFieldsFilled = requiredFields.every(field => 
      formValues[field] && formValues[field].trim()
    );
    const noErrors = Object.keys(validationErrors).length === 0;
    const slugOk = slugAvailable !== false;

    return allRequiredFieldsFilled && noErrors && slugOk;
  };

  // Handle review button click
  handleReview = () => {
    if (!this.isFormValid()) {
      notification.error('Please fix all validation errors before proceeding');
      return;
    }
    this.setState({ showReview: true, isEditing: false });
  };

  // Handle back to form
  handleBackToForm = () => {
    this.setState({ showReview: false, isEditing: false });
  };

  // Toggle edit mode on review page
  toggleEdit = () => {
    this.setState({ isEditing: !this.state.isEditing });
  };

  // Handle form submission
  handleSubmit = async () => {
    const { formValues } = this.state;

    if (!this.isFormValid()) {
      notification.error('Please fix all validation errors before submitting');
      return;
    }

    this.setState({ provisioning: true, currentStep: 0, showReview: false });

    try {
      // Build legacy address field from structured fields for backward compatibility
      const addressParts = [
        formValues.address_line1,
        formValues.address_line2,
        formValues.city,
        formValues.state_province,
        formValues.postal_code,
        formValues.country
      ].filter(part => part && part.trim());
      const legacyAddress = addressParts.join(', ');

      // Prepare data for backend - send all available fields
      const apiData = {
        organization_name: formValues.organization_name,
        address: legacyAddress, // Legacy field for backward compatibility
        address_line1: formValues.address_line1,
        address_line2: formValues.address_line2 || null,
        city: formValues.city || null,
        state_province: formValues.state_province || null,
        postal_code: formValues.postal_code || null,
        country: formValues.country || null,
        contact_first_name: formValues.contact_first_name,
        contact_last_name: formValues.contact_last_name,
        contact_email: formValues.contact_email,
        company_name: formValues.company_name || null,
        contact_phone: formValues.contact_phone || null,
        organization_email: formValues.organization_email || null,
      };

      const response = await $http.post('api/admin/organizations/provision', apiData);

      const stepsCompleted = response.data.steps_completed || [];
      let currentStep = 0;

      if (stepsCompleted.includes('organization_created')) currentStep = 1;
      if (stepsCompleted.includes('vdb_provisioned')) currentStep = 2;
      if (stepsCompleted.includes('user_created')) currentStep = 3;
      if (stepsCompleted.includes('invitation_sent')) currentStep = 4;

      this.setState({
        provisioning: false,
        provisioningComplete: true,
        currentStep: 4,
        provisioningResult: response.data,
      });

      notification.success('Organization provisioned successfully!');
      recordEvent('provision', 'organization', response.data.organization.id);
    } catch (error) {
      console.error('Failed to provision organization:', error);
      
      const errorMessage = error.data?.error || error.message || 'Unknown error occurred';
      const stepsCompleted = error.data?.steps_completed || [];
      
      let currentStep = 0;
      if (stepsCompleted.includes('organization_created')) currentStep = 1;
      if (stepsCompleted.includes('vdb_provisioned')) currentStep = 2;
      if (stepsCompleted.includes('user_created')) currentStep = 3;

      this.setState({
        provisioning: false,
        provisioningError: errorMessage,
        currentStep,
      });

      notification.error('Failed to provision organization: ' + errorMessage);
      this.props.onError(error);
    }
  };

  // Reset form
  handleReset = () => {
    this.setState({
      loading: false,
      provisioning: false,
      provisioningComplete: false,
      provisioningError: null,
      currentStep: 0,
      showReview: false,
      isEditing: false,
      formValues: {
        organization_name: '',
        organization_email: '',
        address: '',
        contact_first_name: '',
        contact_last_name: '',
        contact_email: '',
        contact_phone: '',
        company_name: '',
        country: '',
        address_line1: '',
        address_line2: '',
        city: '',
        state_province: '',
        postal_code: '',
      },
      generatedSlug: '',
      slugAvailable: null,
      slugChecking: false,
      validationErrors: {},
      provisioningResult: null,
    });
  };

  renderProvisioningSteps = () => {
    const { currentStep, provisioning, provisioningError } = this.state;

    const steps = [
      { title: 'Validate', description: 'Validating input' },
      { title: 'Create Org', description: 'Creating organization' },
      { title: 'Provision VDB', description: 'Provisioning VDB' },
      { title: 'Create User', description: 'Creating user account' },
      { title: 'Send Invite', description: 'Sending invitation' },
    ];

    return (
      <Steps current={currentStep} status={provisioningError ? 'error' : provisioning ? 'process' : 'finish'}>
        {steps.map((step, index) => (
          <Step key={index} title={step.title} description={step.description} />
        ))}
      </Steps>
    );
  };

  renderForm = () => {
    const {
      formValues,
      generatedSlug,
      slugAvailable,
      slugChecking,
      validationErrors,
      provisioning,
    } = this.state;

    const sectionStyle = {
      marginBottom: '32px',
      padding: '24px',
      background: '#fafafa',
      border: '1px solid #e8e8e8',
      borderRadius: '4px',
    };

    const sectionHeaderStyle = {
      fontSize: '18px',
      fontWeight: '600',
      color: '#262626',
      marginBottom: '20px',
      paddingBottom: '12px',
      borderBottom: '1px solid #d9d9d9',
    };

    return (
      <Form layout="vertical">
        <Alert
          message="Organization Provisioning"
          description="Create a new customer organization with complete setup including VDB provisioning, user account creation, and invitation email."
          type="info"
          showIcon
          style={{ marginBottom: 24 }}
        />

        {/* Account Details Section */}
        <div style={sectionStyle}>
          <h3 style={sectionHeaderStyle}>Account Details</h3>
          
          <Form.Item
            label="Account Name"
            validateStatus={validationErrors.organization_name ? 'error' : ''}
            help={validationErrors.organization_name || 'This will be the organization name in TableScope'}
            required
          >
            <Input
              placeholder="Enter account name (e.g., Acme Corporation)"
              value={formValues.organization_name}
              onChange={(e) => this.handleFieldChange('organization_name', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          {generatedSlug && (
            <Form.Item
              label="Account Identifier (Slug)"
              validateStatus={
                slugChecking ? 'validating' : slugAvailable === true ? 'success' : slugAvailable === false ? 'error' : ''
              }
              help={
                slugChecking
                  ? 'Checking availability...'
                  : slugAvailable === true
                  ? '✓ Identifier is available'
                  : slugAvailable === false
                  ? '✗ Identifier is already taken - please choose a different account name'
                  : slugAvailable === null && generatedSlug
                  ? 'ℹ Availability check pending or unavailable'
                  : 'Auto-generated from account name'
              }
            >
              <Input value={generatedSlug} disabled />
            </Form.Item>
          )}

          <Form.Item
            label="Email Address Associated with the Account"
            validateStatus={validationErrors.organization_email ? 'error' : ''}
            help={validationErrors.organization_email || 'Primary email for this account'}
          >
            <Input
              type="email"
              placeholder="Enter account email address"
              value={formValues.organization_email}
              onChange={(e) => this.handleFieldChange('organization_email', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>
        </div>

        {/* Contact Information Section */}
        <div style={sectionStyle}>
          <h3 style={sectionHeaderStyle}>Contact Information</h3>
          
          <Form.Item
            label="Full Name"
            required
            style={{ marginBottom: 0 }}
          >
            <Input.Group compact style={{ display: 'flex', gap: '8px' }}>
              <Form.Item
                validateStatus={validationErrors.contact_first_name ? 'error' : ''}
                help={validationErrors.contact_first_name}
                style={{ flex: 1, marginBottom: 24 }}
              >
                <Input
                  placeholder="First name"
                  value={formValues.contact_first_name}
                  onChange={(e) => this.handleFieldChange('contact_first_name', e.target.value)}
                  disabled={provisioning}
                />
              </Form.Item>
              <Form.Item
                validateStatus={validationErrors.contact_last_name ? 'error' : ''}
                help={validationErrors.contact_last_name}
                style={{ flex: 1, marginBottom: 24 }}
              >
                <Input
                  placeholder="Last name"
                  value={formValues.contact_last_name}
                  onChange={(e) => this.handleFieldChange('contact_last_name', e.target.value)}
                  disabled={provisioning}
                />
              </Form.Item>
            </Input.Group>
          </Form.Item>

          <Form.Item
            label="Company Name"
            validateStatus={validationErrors.company_name ? 'error' : ''}
            help={validationErrors.company_name}
          >
            <Input
              placeholder="Enter company name"
              value={formValues.company_name}
              onChange={(e) => this.handleFieldChange('company_name', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="Country"
            validateStatus={validationErrors.country ? 'error' : ''}
            help={validationErrors.country}
          >
            <Input
              placeholder="Enter country"
              value={formValues.country}
              onChange={(e) => this.handleFieldChange('country', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="Address Line 1"
            validateStatus={validationErrors.address_line1 ? 'error' : ''}
            help={validationErrors.address_line1 || 'Street address, P.O. box, company name, c/o'}
            required
          >
            <Input
              placeholder="Enter street address"
              value={formValues.address_line1}
              onChange={(e) => this.handleFieldChange('address_line1', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="Address Line 2"
            validateStatus={validationErrors.address_line2 ? 'error' : ''}
            help={validationErrors.address_line2 || 'Apartment, suite, unit, building, floor, etc.'}
          >
            <Input
              placeholder="Enter apartment, suite, etc. (optional)"
              value={formValues.address_line2}
              onChange={(e) => this.handleFieldChange('address_line2', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="City"
            validateStatus={validationErrors.city ? 'error' : ''}
            help={validationErrors.city}
          >
            <Input
              placeholder="Enter city"
              value={formValues.city}
              onChange={(e) => this.handleFieldChange('city', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="State, Province or Region"
            validateStatus={validationErrors.state_province ? 'error' : ''}
            help={validationErrors.state_province}
          >
            <Input
              placeholder="Enter state or province"
              value={formValues.state_province}
              onChange={(e) => this.handleFieldChange('state_province', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="ZIP or Postal Code"
            validateStatus={validationErrors.postal_code ? 'error' : ''}
            help={validationErrors.postal_code}
          >
            <Input
              placeholder="Enter ZIP or postal code"
              value={formValues.postal_code}
              onChange={(e) => this.handleFieldChange('postal_code', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="Phone Number"
            validateStatus={validationErrors.contact_phone ? 'error' : ''}
            help={validationErrors.contact_phone}
          >
            <Input
              placeholder="Enter phone number"
              value={formValues.contact_phone}
              onChange={(e) => this.handleFieldChange('contact_phone', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>

          <Form.Item
            label="Email"
            validateStatus={validationErrors.contact_email ? 'error' : ''}
            help={validationErrors.contact_email}
            required
          >
            <Input
              type="email"
              placeholder="Enter email address"
              value={formValues.contact_email}
              onChange={(e) => this.handleFieldChange('contact_email', e.target.value)}
              disabled={provisioning}
            />
          </Form.Item>
        </div>

        <Form.Item>
          <Button
            type="primary"
            size="large"
            onClick={this.handleReview}
            disabled={!this.isFormValid() || provisioning}
            block
          >
            Review
          </Button>
        </Form.Item>
      </Form>
    );
  };

  renderReviewPage = () => {
    const { formValues, generatedSlug, isEditing, validationErrors, slugAvailable, slugChecking } = this.state;

    const reviewSectionStyle = {
      marginBottom: '24px',
      padding: '20px',
      background: '#ffffff',
      border: '1px solid #e8e8e8',
      borderRadius: '4px',
    };

    const reviewHeaderStyle = {
      fontSize: '16px',
      fontWeight: '600',
      color: '#262626',
      marginBottom: '16px',
      paddingBottom: '10px',
      borderBottom: '1px solid #e8e8e8',
    };

    const reviewFieldStyle = {
      marginBottom: '12px',
      display: 'flex',
      flexDirection: 'column',
    };

    const labelStyle = {
      fontWeight: '500',
      color: '#595959',
      marginBottom: '4px',
      fontSize: '14px',
    };

    const valueStyle = {
      color: '#262626',
      fontSize: '14px',
    };

    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <h3 style={{ margin: 0 }}>Review Organization Details</h3>
          <Button 
            icon={<EditOutlined />} 
            onClick={this.toggleEdit}
            type={isEditing ? 'default' : 'primary'}
          >
            {isEditing ? 'Cancel Edit' : 'Edit'}
          </Button>
        </div>

        {/* Account Details Section */}
        <div style={reviewSectionStyle}>
          <h4 style={reviewHeaderStyle}>Account Details</h4>
          
          {isEditing ? (
            <>
              <Form.Item
                label="Account Name"
                validateStatus={validationErrors.organization_name ? 'error' : ''}
                help={validationErrors.organization_name}
                required
              >
                <Input
                  value={formValues.organization_name}
                  onChange={(e) => this.handleFieldChange('organization_name', e.target.value)}
                />
              </Form.Item>

              {generatedSlug && (
                <Form.Item
                  label="Account Identifier (Slug)"
                  validateStatus={
                    slugChecking ? 'validating' : slugAvailable === true ? 'success' : slugAvailable === false ? 'error' : ''
                  }
                  help={
                    slugChecking
                      ? 'Checking availability...'
                      : slugAvailable === true
                      ? '✓ Identifier is available'
                      : slugAvailable === false
                      ? '✗ Identifier is already taken'
                      : 'Auto-generated from account name'
                  }
                >
                  <Input value={generatedSlug} disabled />
                </Form.Item>
              )}

              <Form.Item
                label="Email Address Associated with the Account"
                validateStatus={validationErrors.organization_email ? 'error' : ''}
                help={validationErrors.organization_email}
              >
                <Input
                  type="email"
                  value={formValues.organization_email}
                  onChange={(e) => this.handleFieldChange('organization_email', e.target.value)}
                />
              </Form.Item>
            </>
          ) : (
            <>
              <div style={reviewFieldStyle}>
                <span style={labelStyle}>Account Name:</span>
                <span style={valueStyle}>{formValues.organization_name}</span>
              </div>
              <div style={reviewFieldStyle}>
                <span style={labelStyle}>Account Identifier:</span>
                <span style={valueStyle}>{generatedSlug}</span>
              </div>
              {formValues.organization_email && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>Account Email:</span>
                  <span style={valueStyle}>{formValues.organization_email}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Contact Information Section */}
        <div style={reviewSectionStyle}>
          <h4 style={reviewHeaderStyle}>Contact Information</h4>
          
          {isEditing ? (
            <>
              <Form.Item
                label="Full Name"
                required
                style={{ marginBottom: 0 }}
              >
                <Input.Group compact style={{ display: 'flex', gap: '8px' }}>
                  <Form.Item
                    validateStatus={validationErrors.contact_first_name ? 'error' : ''}
                    help={validationErrors.contact_first_name}
                    style={{ flex: 1, marginBottom: 24 }}
                  >
                    <Input
                      placeholder="First name"
                      value={formValues.contact_first_name}
                      onChange={(e) => this.handleFieldChange('contact_first_name', e.target.value)}
                    />
                  </Form.Item>
                  <Form.Item
                    validateStatus={validationErrors.contact_last_name ? 'error' : ''}
                    help={validationErrors.contact_last_name}
                    style={{ flex: 1, marginBottom: 24 }}
                  >
                    <Input
                      placeholder="Last name"
                      value={formValues.contact_last_name}
                      onChange={(e) => this.handleFieldChange('contact_last_name', e.target.value)}
                    />
                  </Form.Item>
                </Input.Group>
              </Form.Item>

              <Form.Item
                label="Company Name"
                validateStatus={validationErrors.company_name ? 'error' : ''}
                help={validationErrors.company_name}
              >
                <Input
                  value={formValues.company_name}
                  onChange={(e) => this.handleFieldChange('company_name', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="Country"
                validateStatus={validationErrors.country ? 'error' : ''}
                help={validationErrors.country}
              >
                <Input
                  value={formValues.country}
                  onChange={(e) => this.handleFieldChange('country', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="Address Line 1"
                validateStatus={validationErrors.address_line1 ? 'error' : ''}
                help={validationErrors.address_line1}
                required
              >
                <Input
                  value={formValues.address_line1}
                  onChange={(e) => this.handleFieldChange('address_line1', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="Address Line 2"
                validateStatus={validationErrors.address_line2 ? 'error' : ''}
                help={validationErrors.address_line2}
              >
                <Input
                  value={formValues.address_line2}
                  onChange={(e) => this.handleFieldChange('address_line2', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="City"
                validateStatus={validationErrors.city ? 'error' : ''}
                help={validationErrors.city}
              >
                <Input
                  value={formValues.city}
                  onChange={(e) => this.handleFieldChange('city', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="State, Province or Region"
                validateStatus={validationErrors.state_province ? 'error' : ''}
                help={validationErrors.state_province}
              >
                <Input
                  value={formValues.state_province}
                  onChange={(e) => this.handleFieldChange('state_province', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="ZIP or Postal Code"
                validateStatus={validationErrors.postal_code ? 'error' : ''}
                help={validationErrors.postal_code}
              >
                <Input
                  value={formValues.postal_code}
                  onChange={(e) => this.handleFieldChange('postal_code', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="Phone Number"
                validateStatus={validationErrors.contact_phone ? 'error' : ''}
                help={validationErrors.contact_phone}
              >
                <Input
                  value={formValues.contact_phone}
                  onChange={(e) => this.handleFieldChange('contact_phone', e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="Email"
                validateStatus={validationErrors.contact_email ? 'error' : ''}
                help={validationErrors.contact_email}
                required
              >
                <Input
                  type="email"
                  value={formValues.contact_email}
                  onChange={(e) => this.handleFieldChange('contact_email', e.target.value)}
                />
              </Form.Item>
            </>
          ) : (
            <>
              <div style={reviewFieldStyle}>
                <span style={labelStyle}>Full Name:</span>
                <span style={valueStyle}>{formValues.contact_first_name} {formValues.contact_last_name}</span>
              </div>
              {formValues.company_name && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>Company Name:</span>
                  <span style={valueStyle}>{formValues.company_name}</span>
                </div>
              )}
              {formValues.country && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>Country:</span>
                  <span style={valueStyle}>{formValues.country}</span>
                </div>
              )}
              <div style={reviewFieldStyle}>
                <span style={labelStyle}>Address Line 1:</span>
                <span style={valueStyle}>{formValues.address_line1}</span>
              </div>
              {formValues.address_line2 && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>Address Line 2:</span>
                  <span style={valueStyle}>{formValues.address_line2}</span>
                </div>
              )}
              {formValues.city && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>City:</span>
                  <span style={valueStyle}>{formValues.city}</span>
                </div>
              )}
              {formValues.state_province && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>State, Province or Region:</span>
                  <span style={valueStyle}>{formValues.state_province}</span>
                </div>
              )}
              {formValues.postal_code && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>ZIP or Postal Code:</span>
                  <span style={valueStyle}>{formValues.postal_code}</span>
                </div>
              )}
              {formValues.contact_phone && (
                <div style={reviewFieldStyle}>
                  <span style={labelStyle}>Phone Number:</span>
                  <span style={valueStyle}>{formValues.contact_phone}</span>
                </div>
              )}
              <div style={reviewFieldStyle}>
                <span style={labelStyle}>Email:</span>
                <span style={valueStyle}>{formValues.contact_email}</span>
              </div>
            </>
          )}
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '24px' }}>
          <Button size="large" onClick={this.handleBackToForm}>
            Back
          </Button>
          <Button 
            type="primary" 
            size="large"
            onClick={this.handleSubmit}
            disabled={!this.isFormValid()}
          >
            Confirm & Provision
          </Button>
        </div>
      </div>
    );
  };

  renderSuccess = () => {
    const { provisioningResult } = this.state;

    if (!provisioningResult) return null;

    const { organization, vdb, user, invitation_sent } = provisioningResult;

    return (
      <Result
        status="success"
        title="Organization Provisioned Successfully!"
        subTitle={`Organization "${organization.name}" has been created and is ready to use.`}
        extra={[
          <Button type="primary" key="new" onClick={this.handleReset}>
            Provision Another Organization
          </Button>,
        ]}
      >
        <div style={{ textAlign: 'left', maxWidth: 600, margin: '0 auto' }}>
          <Card title="Organization Details" size="small" style={{ marginBottom: 16 }}>
            <p><strong>Name:</strong> {organization.name}</p>
            <p><strong>Slug:</strong> {organization.slug}</p>
            <p><strong>Address:</strong> {organization.address}</p>
            <p><strong>Primary Contact:</strong> {organization.primary_contact_first_name} {organization.primary_contact_last_name}</p>
            <p><strong>Email:</strong> {organization.primary_contact_email}</p>
          </Card>

          {vdb && (
            <Card title="VDB Configuration" size="small" style={{ marginBottom: 16 }}>
              <p><strong>VDB ID:</strong> {vdb.vdb_id}</p>
              <p><strong>Status:</strong> {vdb.status}</p>
              <p><strong>Provisioned:</strong> {vdb.provisioned ? 'Yes' : 'No'}</p>
            </Card>
          )}

          {user && (
            <Card title="User Account" size="small" style={{ marginBottom: 16 }}>
              <p><strong>Name:</strong> {user.name}</p>
              <p><strong>Email:</strong> {user.email}</p>
              <p><strong>Invitation Sent:</strong> {invitation_sent ? 'Yes' : 'No'}</p>
              <p><strong>Status:</strong> {user.is_invitation_pending ? 'Pending' : 'Active'}</p>
            </Card>
          )}
        </div>
      </Result>
    );
  };

  renderError = () => {
    const { provisioningError } = this.state;

    return (
      <Result
        status="error"
        title="Provisioning Failed"
        subTitle={provisioningError}
        extra={[
          <Button type="primary" key="retry" onClick={this.handleReset}>
            Try Again
          </Button>,
        ]}
      />
    );
  };

  render() {
    const { provisioning, provisioningComplete, provisioningError, showReview } = this.state;

    return (
      <div className="container">
        <div className="page-header">
          <h3>Organization Provisioning</h3>
        </div>

        <div style={{ maxWidth: 800, margin: '0 auto', padding: '20px' }}>
          {(provisioning || provisioningComplete || provisioningError) && (
            <Card style={{ marginBottom: 24 }}>
              {this.renderProvisioningSteps()}
            </Card>
          )}

          {provisioningComplete && !provisioningError ? (
            this.renderSuccess()
          ) : provisioningError ? (
            this.renderError()
          ) : showReview ? (
            <Card>{this.renderReviewPage()}</Card>
          ) : (
            <Card>{this.renderForm()}</Card>
          )}
        </div>
      </div>
    );
  }
}

export default function init(ngModule) {
  ngModule.component('pageOrganizationProvisioning', react2angular(OrganizationProvisioning));

  return routesToAngularRoutes(
    [
      {
        path: '/admin/organization-provisioning',
        title: 'Organization Provisioning',
        key: 'organization_provisioning',
      },
    ],
    {
      template: '<page-organization-provisioning on-error="handleError"></page-organization-provisioning>',
      controller($scope, $exceptionHandler) {
        'ngInject';

        $scope.handleError = $exceptionHandler;
      },
    }
  );
}

init.init = true;
