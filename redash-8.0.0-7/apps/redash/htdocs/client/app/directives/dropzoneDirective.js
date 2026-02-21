import React from 'react';
import ReactDOM from 'react-dom';
import DropzonePage from '../pages/dropzone/DropzonePage';

export default function (ngModule) {
  ngModule.directive('dropzone', () => ({
    restrict: 'E',
    link(scope, element) {
      ReactDOM.render(<DropzonePage />, element[0]);
      console.log('Dropzone directive initialized'); // eslint-disable-line no-console
      // Clean up when directive is destroyed
      scope.$on('$destroy', () => {
        ReactDOM.unmountComponentAtNode(element[0]);
      });
    },
  }));
}
