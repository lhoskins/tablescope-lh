import { each, values, map, includes, first } from 'lodash';
import React from 'react';
import PropTypes from 'prop-types';
import Select from 'antd/lib/select';
import Modal from 'antd/lib/modal';
import { wrap as wrapDialog, DialogPropType } from '@/components/DialogWrapper';
import {
  MappingType,
  ParameterMappingListInput,
} from '@/components/ParameterMappingInput';

import notification from '@/services/notification';

import { Query } from '@/services/query';

const { Option, OptGroup } = Select;

const getOrgSlug = () => window.location.pathname.split('/')[1] || 'default';

class AddWidgetDialog extends React.Component {
  static propTypes = {
    dashboard: PropTypes.object.isRequired, // eslint-disable-line react/forbid-prop-types
    dialog: DialogPropType.isRequired,
    onConfirm: PropTypes.func.isRequired,
  };

  state = {
    saveInProgress: false,
    selectedQuery: null,
    selectedVis: null,
    parameterMappings: [],
    availableQueries: [],
    loadingQueries: true,
  };

  componentDidMount() {
    this.fetchQueriesForProject();
  }

  fetchQueriesForProject() {
    const { dashboard } = this.props;
    let projectIds = dashboard.project_id;
    
    console.log('[AddWidgetDialog] Dashboard:', dashboard);
    console.log('[AddWidgetDialog] Dashboard project_id (raw):', projectIds);
    console.log('[AddWidgetDialog] project_id type:', typeof projectIds);
    
    // Normalize project_id to array
    if (projectIds) {
      if (!Array.isArray(projectIds)) {
        projectIds = [projectIds];
      }
      console.log('[AddWidgetDialog] Normalized project_id:', projectIds);
    }
    
    // If dashboard has project_id, fetch queries from those projects
    if (projectIds && projectIds.length > 0) {
      console.log('[AddWidgetDialog] Fetching queries for projects:', projectIds);
      
      // Fetch queries from all assigned projects
      const fetchPromises = projectIds.map(projectId => {
        const url = `/${getOrgSlug()}/api/projects/${projectId}/items`;
        console.log('[AddWidgetDialog] Fetching from:', url);
        
        return fetch(url)
          .then(r => r.ok ? r.json() : Promise.reject(r.status))
          .then(data => {
            console.log(`[AddWidgetDialog] Project ${projectId} returned:`, data);
            console.log(`[AddWidgetDialog] Project ${projectId} queries:`, data.queries);
            return data.queries || [];
          })
          .catch(err => {
            console.error(`Failed to fetch queries for project ${projectId}:`, err);
            return [];
          });
      });
      
      Promise.all(fetchPromises).then(results => {
        console.log('[AddWidgetDialog] All results:', results);
        
        // Flatten and deduplicate queries
        const allQueries = results.flat();
        console.log('[AddWidgetDialog] Flattened queries:', allQueries);
        
        const uniqueQueries = allQueries.filter((q, index, self) =>
          index === self.findIndex(t => t.id === q.id)
        );
        console.log('[AddWidgetDialog] Unique queries:', uniqueQueries);
        
        // Filter out drafts
        const nonDraftQueries = uniqueQueries.filter(q => !q.is_draft);
        console.log('[AddWidgetDialog] Non-draft queries:', nonDraftQueries);
        
        this.setState({
          availableQueries: nonDraftQueries,
          loadingQueries: false,
        });
      });
    } else {
      console.log('[AddWidgetDialog] No project_id, using Query.recent() fallback');
      
      // No project assigned, use Query.recent() as fallback
      Query.recent().$promise.then((results) => {
        console.log('[AddWidgetDialog] Query.recent() results:', results);
        const filteredResults = results.filter(item => !item.is_draft);
        this.setState({
          availableQueries: filteredResults,
          loadingQueries: false,
        });
      }).catch(() => {
        this.setState({
          availableQueries: [],
          loadingQueries: false,
        });
      });
    }
  }

  selectQuery(queryId) {
    // Clear previously selected query (if any)
    this.setState({
      selectedQuery: null,
      selectedVis: null,
      parameterMappings: [],
    });

    if (queryId) {
      Query.get({ id: queryId }, (query) => {
        if (query) {
          const existingParamNames = map(
            this.props.dashboard.getParametersDefs(),
            param => param.name,
          );
          this.setState({
            selectedQuery: query,
            parameterMappings: map(query.getParametersDefs(), param => ({
              name: param.name,
              type: includes(existingParamNames, param.name)
                ? MappingType.DashboardMapToExisting : MappingType.DashboardAddNew,
              mapTo: param.name,
              value: param.normalizedValue,
              title: '',
              param,
            })),
          });
          if (query.visualizations.length) {
            this.setState({ selectedVis: query.visualizations[0] });
          }
        }
      });
    }
  }

  selectVisualization(query, visualizationId) {
    each(query.visualizations, (visualization) => {
      if (visualization.id === visualizationId) {
        this.setState({ selectedVis: visualization });
        return false;
      }
    });
  }

  saveWidget() {
    const { selectedVis, parameterMappings } = this.state;

    this.setState({ saveInProgress: true });

    this.props.onConfirm(selectedVis, parameterMappings)
      .then(() => {
        this.props.dialog.close();
      })
      .catch(() => {
        notification.error('Widget could not be added');
      })
      .finally(() => {
        this.setState({ saveInProgress: false });
      });
  }

  updateParamMappings(parameterMappings) {
    this.setState({ parameterMappings });
  }

  renderVisualizationInput() {
    let visualizationGroups = {};
    if (this.state.selectedQuery) {
      each(this.state.selectedQuery.visualizations, (vis) => {
        visualizationGroups[vis.type] = visualizationGroups[vis.type] || [];
        visualizationGroups[vis.type].push(vis);
      });
    }
    visualizationGroups = values(visualizationGroups);
    return (
      <div>
        <div className="form-group">
          <label htmlFor="choose-visualization">Choose Visualization</label>
          <Select
            id="choose-visualization"
            className="w-100"
            defaultValue={first(this.state.selectedQuery.visualizations).id}
            onChange={visualizationId => this.selectVisualization(this.state.selectedQuery, visualizationId)}
          >
            {visualizationGroups.map(visualizations => (
              <OptGroup label={visualizations[0].type} key={visualizations[0].type}>
                {visualizations.map(visualization => (
                  <Option value={visualization.id} key={visualization.id}>{visualization.name}</Option>
                ))}
              </OptGroup>
            ))}
          </Select>
        </div>
      </div>
    );
  }

  render() {
    const existingParams = this.props.dashboard.getParametersDefs();
    const { dialog } = this.props;
    const { availableQueries, loadingQueries } = this.state;

    return (
      <Modal
        {...dialog.props}
        title="Add Widget"
        onOk={() => this.saveWidget()}
        okButtonProps={{
          loading: this.state.saveInProgress,
          disabled: !this.state.selectedQuery,
        }}
        okText="Add to Dashboard"
        width={700}
      >
        <div data-test="AddWidgetDialog">
          {/* Query Selector */}
          <div className="form-group">
            <label htmlFor="choose-query">Choose Query</label>
            <Select
              id="choose-query"
              className="w-100"
              placeholder={loadingQueries ? "Loading queries..." : "Select a query"}
              value={this.state.selectedQuery ? this.state.selectedQuery.id : undefined}
              onChange={queryId => this.selectQuery(queryId)}
              showSearch
              filterOption={(input, option) => {
                if (!option || !option.children) return false;
                const children = typeof option.children === 'string' ? option.children : '';
                return children.toLowerCase().indexOf(input.toLowerCase()) >= 0;
              }}
              loading={loadingQueries}
              disabled={loadingQueries}
            >
              {availableQueries.map(q => (
                <Option value={q.id} key={q.id}>
                  {q.name}
                </Option>
              ))}
            </Select>
          </div>

          {this.state.selectedQuery && this.renderVisualizationInput()}

          {
            (this.state.parameterMappings.length > 0) && [
              <label key="parameters-title" htmlFor="parameter-mappings">Parameters</label>,
              <ParameterMappingListInput
                key="parameters-list"
                id="parameter-mappings"
                mappings={this.state.parameterMappings}
                existingParams={existingParams}
                onChange={mappings => this.updateParamMappings(mappings)}
              />,
            ]
          }
        </div>
      </Modal>
    );
  }
}

export default wrapDialog(AddWidgetDialog);
