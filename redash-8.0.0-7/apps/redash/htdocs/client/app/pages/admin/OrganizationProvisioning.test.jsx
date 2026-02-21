import React from 'react';
import { mount } from 'enzyme';
import OrganizationProvisioning from './OrganizationProvisioning';

// Mock services
jest.mock('@/services/ng', () => ({
  $http: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

jest.mock('@/services/recordEvent', () => jest.fn());
jest.mock('@/services/notification', () => ({
  success: jest.fn(),
  error: jest.fn(),
}));

describe('OrganizationProvisioning', () => {
  let wrapper;
  const mockOnError = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Form Validation', () => {
    test('validates organization name length', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      // Test too short
      expect(instance.validateOrganizationName('ab')).toBe(false);

      // Test valid
      expect(instance.validateOrganizationName('Acme Corp')).toBe(true);

      // Test too long
      const longName = 'a'.repeat(256);
      expect(instance.validateOrganizationName(longName)).toBe(false);
    });

    test('validates email format', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      // Test invalid emails
      expect(instance.validateEmail('invalid')).toBe(false);
      expect(instance.validateEmail('invalid@')).toBe(false);
      expect(instance.validateEmail('@example.com')).toBe(false);

      // Test valid email
      expect(instance.validateEmail('john@example.com')).toBe(true);
    });

    test('validates name fields', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      // Test invalid names
      expect(instance.validateName('', 'First name')).toBe(false);
      expect(instance.validateName('John123', 'First name')).toBe(false);

      // Test valid names
      expect(instance.validateName('John', 'First name')).toBe(true);
      expect(instance.validateName("O'Brien", 'Last name')).toBe(true);
      expect(instance.validateName('Mary-Jane', 'First name')).toBe(true);
    });
  });

  describe('Slug Generation', () => {
    test('generates slug from organization name', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      expect(instance.generateSlug('Acme Corporation')).toBe('acme-corporation');
      expect(instance.generateSlug('Test & Company')).toBe('test-company');
      expect(instance.generateSlug('  Multiple   Spaces  ')).toBe('multiple-spaces');
      expect(instance.generateSlug('UPPERCASE')).toBe('uppercase');
    });

    test('handles special characters in slug generation', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      expect(instance.generateSlug('Test@#$%Company')).toBe('testcompany');
      expect(instance.generateSlug('Test---Company')).toBe('test-company');
    });
  });

  describe('Form State Management', () => {
    test('updates form values on field change', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      instance.handleFieldChange('organization_name', 'Test Org');

      expect(instance.state.formValues.organization_name).toBe('Test Org');
    });

    test('auto-generates slug when organization name changes', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      instance.handleFieldChange('organization_name', 'Test Organization');

      expect(instance.state.generatedSlug).toBe('test-organization');
    });
  });

  describe('Form Submission', () => {
    test('disables submit button when form is invalid', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      // Empty form should be invalid
      expect(instance.isFormValid()).toBe(false);
    });

    test('enables submit button when form is valid', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      // Set valid form values
      instance.setState({
        formValues: {
          organization_name: 'Test Org',
          address: '123 Main St',
          contact_first_name: 'John',
          contact_last_name: 'Doe',
          contact_email: 'john@example.com',
        },
        slugAvailable: true,
        emailAvailable: true,
        validationErrors: {},
      });

      expect(instance.isFormValid()).toBe(true);
    });
  });

  describe('Progress Indicator', () => {
    test('shows provisioning steps during submission', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      instance.setState({ provisioning: true, currentStep: 2 });
      wrapper.update();

      // Check that Steps component is rendered
      expect(wrapper.find('Steps').length).toBeGreaterThan(0);
    });
  });

  describe('Success Display', () => {
    test('shows success message after provisioning', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      const mockResult = {
        organization: {
          id: 1,
          name: 'Test Org',
          slug: 'test-org',
          address: '123 Main St',
          primary_contact_first_name: 'John',
          primary_contact_last_name: 'Doe',
          primary_contact_email: 'john@example.com',
        },
        vdb: {
          vdb_id: '1234567',
          status: 'active',
          provisioned: true,
        },
        user: {
          id: 1,
          email: 'john@example.com',
          name: 'John Doe',
          is_invitation_pending: true,
        },
        invitation_sent: true,
      };

      instance.setState({
        provisioningComplete: true,
        provisioningResult: mockResult,
      });
      wrapper.update();

      // Check that Result component is rendered with success status
      expect(wrapper.find('Result').prop('status')).toBe('success');
    });
  });

  describe('Error Display', () => {
    test('shows error message when provisioning fails', () => {
      wrapper = mount(<OrganizationProvisioning onError={mockOnError} />);
      const instance = wrapper.instance();

      instance.setState({
        provisioningError: 'Test error message',
      });
      wrapper.update();

      // Check that error is displayed
      expect(wrapper.find('Result').prop('status')).toBe('error');
    });
  });
});
