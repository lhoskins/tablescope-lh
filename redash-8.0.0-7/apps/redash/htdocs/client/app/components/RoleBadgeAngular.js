import { react2angular } from 'react2angular';
import RoleBadge from './RoleBadge';

export default function init(ngModule) {
  ngModule.component('roleBadge', react2angular(RoleBadge, ['role', 'className']));
}

init.init = true;
