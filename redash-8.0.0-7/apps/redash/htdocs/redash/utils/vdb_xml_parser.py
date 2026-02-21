"""
VDB XML Parser Utility

Utility for parsing and manipulating VDB XML files for data migration.
Supports extracting, adding, and removing foreign tables and views from VDB configurations.
"""

import os
import shutil
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from redash.utils.file_permissions import FilePermissionManager

logger = logging.getLogger(__name__)


class VDBXMLParser(object):
    """
    Utility for parsing and manipulating VDB XML files.
    
    This class provides methods to:
    - Read and write VDB XML files
    - Extract foreign table DDL from VDB
    - Add foreign table DDL to VDB
    - Remove foreign table DDL from VDB
    - Extract view DDL from VDB
    - Add view DDL to VDB
    - Remove view DDL from VDB
    """
    
    def __init__(self):
        """Initialize VDB XML Parser."""
        pass
    
    def read_vdb(self, vdb_path):
        """
        Read VDB XML file and return parsed XML tree.
        
        Properly handles CDATA sections in metadata elements.
        
        Args:
            vdb_path: Path to VDB XML file
            
        Returns:
            ElementTree: Parsed XML tree
            
        Raises:
            FileNotFoundError: If VDB file does not exist
            ET.ParseError: If XML is malformed
        """
        if not os.path.exists(vdb_path):
            raise FileNotFoundError('VDB file not found: {}'.format(vdb_path))
        
        try:
            tree = ET.parse(vdb_path)
            
            # Strip CDATA markers from metadata text for easier manipulation
            # We'll add them back when writing
            root = tree.getroot()
            for metadata in root.findall('.//metadata[@type="DDL"]'):
                if metadata.text:
                    # Remove CDATA markers if present
                    text = metadata.text.strip()
                    if text.startswith('<![CDATA[') and text.endswith(']]>'):
                        # Extract content between CDATA markers
                        metadata.text = text[9:-3].strip()  # Remove <![CDATA[ and ]]>
                        logger.debug('Stripped CDATA markers from metadata for processing')
            
            logger.debug('Successfully read VDB file: {}'.format(vdb_path))
            return tree
        except ET.ParseError as e:
            logger.error('Failed to parse VDB XML: {}'.format(str(e)))
            raise
    
    def write_vdb(self, vdb_path, xml_tree):
        """
        Write XML tree to VDB file with backup.
        
        Creates a backup of the existing VDB file before writing the new content.
        Properly wraps metadata DDL content in CDATA sections.
        Preserves XML comments including ParentDirectory paths.
        Sets appropriate file permissions after writing.
        
        Args:
            vdb_path: Path to VDB XML file
            xml_tree: ElementTree to write
            
        Raises:
            IOError: If file cannot be written
        """
        try:
            # Create backup before writing
            if os.path.exists(vdb_path):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_path = '{}.backup_{}'.format(vdb_path, timestamp)
                shutil.copy2(vdb_path, backup_path)
                logger.info('Created VDB backup: {}'.format(backup_path))
            
            # Write XML first without CDATA wrapping
            # Note: ET.indent is available in Python 3.9+, for older versions we write as-is
            try:
                ET.indent(xml_tree, space='  ')
            except AttributeError:
                # Python < 3.9 doesn't have ET.indent
                pass
            
            # Write to string
            # Use 'utf-8' encoding for Python 2 compatibility (Python 2 doesn't support 'unicode' encoding)
            xml_bytes = ET.tostring(xml_tree.getroot(), encoding='utf-8', method='xml')
            # Decode bytes to string for text manipulation
            xml_string = xml_bytes.decode('utf-8') if isinstance(xml_bytes, bytes) else xml_bytes
            
            # Now wrap metadata DDL content in CDATA using text manipulation
            # This preserves the exact format needed by Teiid
            import re
            
            # Pattern to find metadata DDL content that needs CDATA wrapping
            # Match: <metadata type="DDL">CONTENT</metadata>
            # Where CONTENT doesn't already have CDATA
            def wrap_in_cdata(match):
                opening_tag = match.group(1)
                content = match.group(2)
                closing_tag = match.group(3)
                
                # Check if already has CDATA
                if '<![CDATA[' in content:
                    return match.group(0)  # Return unchanged
                
                # Wrap in CDATA
                return '{}<![CDATA[\n{}\n]]>{}'.format(opening_tag, content.strip(), closing_tag)
            
            # Apply CDATA wrapping
            pattern = r'(<metadata type="DDL">)(.*?)(</metadata>)'
            xml_string = re.sub(pattern, wrap_in_cdata, xml_string, flags=re.DOTALL)
            
            # Write to file with XML declaration
            # Use io.open for Python 2/3 compatibility
            import io
            with io.open(vdb_path, 'w', encoding='utf-8') as f:
                f.write(u'<?xml version="1.0" encoding="UTF-8"?>\n')
                # Ensure xml_string is unicode/str for writing
                if isinstance(xml_string, bytes):
                    xml_string = xml_string.decode('utf-8')
                f.write(xml_string)
            
            # Set appropriate file permissions using FilePermissionManager
            # This allows both the Redash process and Wildfly to access the file
            FilePermissionManager.ensure_vdb_file_permissions(vdb_path)
            
            logger.info('Updated VDB file with CDATA-wrapped DDL: {}'.format(vdb_path))
            
        except IOError as e:
            logger.error('Failed to write VDB file: {}'.format(str(e)))
            raise
    
    def update_parent_directory_paths(self, vdb_path, old_path, new_path):
        """
        Update ParentDirectory paths in model comments.
        
        This method updates the ParentDirectory path in XML comments for
        ExcelSourceModel and CSVSourceModel elements. These comments tell
        Teiid where to find the data files.
        
        Since ElementTree doesn't preserve comments, we manipulate the file as text.
        
        Args:
            vdb_path: Path to VDB XML file
            old_path: Old parent directory path (e.g., /customers/31/69/uploads)
            new_path: New parent directory path (e.g., /customers/31/uploads)
            
        Returns:
            bool: True if paths were updated, False otherwise
        """
        try:
            # Read VDB file as text
            # Use io.open for Python 2/3 compatibility
            import io
            with io.open(vdb_path, 'r', encoding='utf-8') as f:
                vdb_content = f.read()
            
            # Create backup
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = '{}.backup_parentdir_{}'.format(vdb_path, timestamp)
            with io.open(backup_path, 'w', encoding='utf-8') as f:
                f.write(vdb_content)
            logger.info('Created ParentDirectory update backup: {}'.format(backup_path))
            
            # Update ParentDirectory paths in comments
            # Pattern: <!-- Uses resource adapter from standalone.xml (ParentDirectory=/path) -->
            import re
            
            # Find and replace ParentDirectory paths
            pattern = r'(ParentDirectory=)' + re.escape(old_path)
            replacement = r'\1' + new_path
            
            updated_content, count = re.subn(pattern, replacement, vdb_content)
            
            if count > 0:
                # Write updated content
                with io.open(vdb_path, 'w', encoding='utf-8') as f:
                    f.write(updated_content)
                
                logger.info('Updated {} ParentDirectory paths from {} to {}'.format(
                    count, old_path, new_path
                ))
                return True
            else:
                logger.warning('No ParentDirectory paths found to update in {}'.format(vdb_path))
                return False
                
        except Exception as e:
            logger.error('Failed to update ParentDirectory paths: {}'.format(str(e)))
            raise
    
    def extract_foreign_table(self, xml_tree, table_name):
        """
        Extract foreign table DDL from VDB XML.
        
        Searches through all models in the VDB to find the foreign table
        definition and extracts its DDL.
        
        Args:
            xml_tree: ElementTree of VDB XML
            table_name: Name of the foreign table to extract
            
        Returns:
            str: Foreign table DDL, or None if not found
        """
        root = xml_tree.getroot()
        
        # Find the model containing the foreign table
        for model in root.findall('.//model'):
            for metadata in model.findall('.//metadata'):
                ddl = metadata.text
                if ddl and 'CREATE FOREIGN TABLE {}'.format(table_name) in ddl:
                    # Extract just this table's DDL
                    extracted_ddl = self._extract_table_ddl(ddl, table_name)
                    if extracted_ddl:
                        logger.debug('Extracted foreign table DDL for: {}'.format(table_name))
                        return extracted_ddl
        
        logger.warning('Foreign table not found in VDB: {}'.format(table_name))
        return None
    
    def add_foreign_table(self, xml_tree, table_ddl):
        """
        Add foreign table DDL to VDB XML.
        
        Finds or creates an appropriate source model and adds the foreign table DDL.
        
        Args:
            xml_tree: ElementTree of VDB XML
            table_ddl: Foreign table DDL to add
            
        Returns:
            ElementTree: Updated XML tree
        """
        root = xml_tree.getroot()
        
        # Find the appropriate model (e.g., ExcelSourceModel or CSVSourceModel)
        model = self._find_or_create_source_model(root)
        
        # Find or create metadata element
        metadata = model.find('.//metadata')
        if metadata is None:
            metadata = ET.SubElement(model, 'metadata', type='DDL')
            metadata.text = ''
        
        # Append table DDL
        if metadata.text:
            metadata.text += '\n\n' + table_ddl
        else:
            metadata.text = table_ddl
        
        logger.debug('Added foreign table DDL to VDB')
        return xml_tree
    
    def remove_foreign_table(self, xml_tree, table_name):
        """
        Remove foreign table DDL from VDB XML.
        
        Searches through all models and removes the specified foreign table DDL.
        
        Args:
            xml_tree: ElementTree of VDB XML
            table_name: Name of the foreign table to remove
            
        Returns:
            ElementTree: Updated XML tree
        """
        root = xml_tree.getroot()
        
        for model in root.findall('.//model'):
            for metadata in model.findall('.//metadata'):
                if metadata.text:
                    # Remove the table DDL
                    updated_text = self._remove_table_ddl(metadata.text, table_name)
                    if updated_text != metadata.text:
                        metadata.text = updated_text
                        logger.debug('Removed foreign table DDL for: {}'.format(table_name))
        
        return xml_tree
    
    def extract_view(self, xml_tree, view_name):
        """
        Extract view DDL from VDB XML.
        
        Searches through virtual models in the VDB to find the view
        definition and extracts its DDL.
        
        Args:
            xml_tree: ElementTree of VDB XML
            view_name: Name of the view to extract
            
        Returns:
            str: View DDL, or None if not found
        """
        root = xml_tree.getroot()
        
        # Find the view model (type="VIRTUAL")
        for model in root.findall('.//model[@type="VIRTUAL"]'):
            for metadata in model.findall('.//metadata'):
                ddl = metadata.text
                if ddl and 'CREATE VIEW {}'.format(view_name) in ddl:
                    extracted_ddl = self._extract_view_ddl(ddl, view_name)
                    if extracted_ddl:
                        logger.debug('Extracted view DDL for: {}'.format(view_name))
                        return extracted_ddl
        
        logger.warning('View not found in VDB: {}'.format(view_name))
        return None
    
    def add_view(self, xml_tree, view_ddl):
        """
        Add view DDL to VDB XML.
        
        Finds or creates a virtual model and adds the view DDL.
        
        Args:
            xml_tree: ElementTree of VDB XML
            view_ddl: View DDL to add
            
        Returns:
            ElementTree: Updated XML tree
        """
        root = xml_tree.getroot()
        
        # Find or create virtual model
        model = self._find_or_create_virtual_model(root)
        
        # Find or create metadata element
        metadata = model.find('.//metadata')
        if metadata is None:
            metadata = ET.SubElement(model, 'metadata', type='DDL')
            metadata.text = ''
        
        # Append view DDL
        if metadata.text:
            metadata.text += '\n\n' + view_ddl
        else:
            metadata.text = view_ddl
        
        logger.debug('Added view DDL to VDB')
        return xml_tree
    
    def remove_view(self, xml_tree, view_name):
        """
        Remove view DDL from VDB XML.
        
        Searches through virtual models and removes the specified view DDL.
        
        Args:
            xml_tree: ElementTree of VDB XML
            view_name: Name of the view to remove
            
        Returns:
            ElementTree: Updated XML tree
        """
        root = xml_tree.getroot()
        
        for model in root.findall('.//model[@type="VIRTUAL"]'):
            for metadata in model.findall('.//metadata'):
                if metadata.text:
                    updated_text = self._remove_view_ddl(metadata.text, view_name)
                    if updated_text != metadata.text:
                        metadata.text = updated_text
                        logger.debug('Removed view DDL for: {}'.format(view_name))
        
        return xml_tree
    
    def _extract_table_ddl(self, full_ddl, table_name):
        """
        Extract specific table DDL from full DDL text.
        
        Args:
            full_ddl: Full DDL text containing multiple statements
            table_name: Name of the table to extract
            
        Returns:
            str: Extracted table DDL, or None if not found
        """
        lines = full_ddl.split('\n')
        table_lines = []
        in_table = False
        paren_count = 0
        
        for line in lines:
            if 'CREATE FOREIGN TABLE {}'.format(table_name) in line:
                in_table = True
            
            if in_table:
                table_lines.append(line)
                
                # Count parentheses to handle nested structures
                paren_count += line.count('(') - line.count(')')
                
                # End of table definition (semicolon at end and balanced parens)
                if line.strip().endswith(';') and paren_count == 0:
                    break
        
        if table_lines:
            return '\n'.join(table_lines)
        return None
    
    def _remove_table_ddl(self, full_ddl, table_name):
        """
        Remove specific table DDL from full DDL text.
        
        Args:
            full_ddl: Full DDL text containing multiple statements
            table_name: Name of the table to remove
            
        Returns:
            str: DDL text with table removed
        """
        lines = full_ddl.split('\n')
        result_lines = []
        skip_table = False
        paren_count = 0
        
        for line in lines:
            if 'CREATE FOREIGN TABLE {}'.format(table_name) in line:
                skip_table = True
                paren_count = 0
            
            if skip_table:
                # Count parentheses to handle nested structures
                paren_count += line.count('(') - line.count(')')
                
                # End of table definition
                if line.strip().endswith(';') and paren_count == 0:
                    skip_table = False
                continue
            
            result_lines.append(line)
        
        # Clean up extra blank lines
        result = '\n'.join(result_lines)
        # Remove multiple consecutive blank lines
        while '\n\n\n' in result:
            result = result.replace('\n\n\n', '\n\n')
        
        return result.strip()
    
    def _extract_view_ddl(self, full_ddl, view_name):
        """
        Extract specific view DDL from full DDL text.
        
        Args:
            full_ddl: Full DDL text containing multiple statements
            view_name: Name of the view to extract
            
        Returns:
            str: Extracted view DDL, or None if not found
        """
        lines = full_ddl.split('\n')
        view_lines = []
        in_view = False
        paren_count = 0
        
        for line in lines:
            if 'CREATE VIEW {}'.format(view_name) in line:
                in_view = True
            
            if in_view:
                view_lines.append(line)
                
                # Count parentheses to handle nested structures
                paren_count += line.count('(') - line.count(')')
                
                # End of view definition (semicolon at end and balanced parens)
                if line.strip().endswith(';') and paren_count == 0:
                    break
        
        if view_lines:
            return '\n'.join(view_lines)
        return None
    
    def _remove_view_ddl(self, full_ddl, view_name):
        """
        Remove specific view DDL from full DDL text.
        
        Args:
            full_ddl: Full DDL text containing multiple statements
            view_name: Name of the view to remove
            
        Returns:
            str: DDL text with view removed
        """
        lines = full_ddl.split('\n')
        result_lines = []
        skip_view = False
        paren_count = 0
        
        for line in lines:
            if 'CREATE VIEW {}'.format(view_name) in line:
                skip_view = True
                paren_count = 0
            
            if skip_view:
                # Count parentheses to handle nested structures
                paren_count += line.count('(') - line.count(')')
                
                # End of view definition
                if line.strip().endswith(';') and paren_count == 0:
                    skip_view = False
                continue
            
            result_lines.append(line)
        
        # Clean up extra blank lines
        result = '\n'.join(result_lines)
        # Remove multiple consecutive blank lines
        while '\n\n\n' in result:
            result = result.replace('\n\n\n', '\n\n')
        
        return result.strip()
    
    def _find_or_create_source_model(self, root):
        """
        Find or create source model for foreign tables.
        
        Args:
            root: Root element of VDB XML
            
        Returns:
            Element: Source model element
        """
        # Look for existing source models
        model = root.find('.//model[@name="ExcelSourceModel"]')
        if model is None:
            model = root.find('.//model[@name="CSVSourceModel"]')
        if model is None:
            model = root.find('.//model[@name="SourceModel"]')
        if model is None:
            # Look for any physical model
            model = root.find('.//model[@type="PHYSICAL"]')
        
        if model is None:
            # Create new source model
            model = ET.SubElement(root, 'model', name='SourceModel', type='PHYSICAL')
            logger.debug('Created new source model in VDB')
        
        return model
    
    def _find_or_create_virtual_model(self, root):
        """
        Find or create virtual model for views.
        
        Args:
            root: Root element of VDB XML
            
        Returns:
            Element: Virtual model element
        """
        # Look for existing virtual model
        model = root.find('.//model[@type="VIRTUAL"]')
        
        if model is None:
            # Create new virtual model
            model = ET.SubElement(root, 'model', name='ViewModel', type='VIRTUAL')
            logger.debug('Created new virtual model in VDB')
        
        return model
