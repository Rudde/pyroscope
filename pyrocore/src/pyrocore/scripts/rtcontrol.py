""" PyroCore - rTorrent Control.

    Copyright (c) 2010 The PyroScope Project <pyroscope.project@gmail.com>

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License along
    with this program; if not, write to the Free Software Foundation, Inc.,
    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
import os
import re
import sys
import operator

from pyrocore import config
from pyrocore.util import fmt
from pyrocore.util.types import Bunch
from pyrocore.scripts.base import ScriptBase, ScriptBaseWithConfig, PromptDecorator
from pyrocore.torrent import engine 


class RtorrentControl(ScriptBaseWithConfig):
    ### Keep things wrapped to fit under this comment... ##############################
    """ 
        Control and inspect rTorrent from the command line.
    
        Filter expressions take the form "<field>=<value>", and all expressions must
        be met (AND). If a field name is omitted, "name" is assumed.
        
        For numeric fields, a leading "+" means greater than, a leading "-" means less 
        than. For string fields, the value is a glob pattern (*, ?, [a-z], [!a-z]).
        Multiple values separated by a comma indicate several possible choices (OR).
        "!" in front of a filter value negates it (NOT).
        
        Examples:
          All 1:1 seeds         ratio=+1
          All active torrents   xfer=+0
          All seeding torrents  up=+0
          Slow torrents         down=+0 down=-5k
          Older than 2 weeks    completed=+2w
          Big stuff             size=+4g
          1:1 seeds not on NAS  ratio=+1 'realpath=!/mnt/*'
    """
    ##      Music                 kind=flac,mp3

    # argument description for the usage information
    ARGS_HELP = "<filter>..."

    # additonal stuff appended after the command handler's docstring
    ADDITIONAL_HELP = ["", "", "Use --help-fields to list all fields and their description."]

    # choices for --ignore
    IGNORE_OPTIONS = ('0', '1')

    # action options that perform some change on selected items
    ACTION_MODES = ( 
        Bunch(name="start", options=("-S", "--start"), help="start torrent"), 
        Bunch(name="close", options=("-C", "--close", "--stop"), help="stop torrent", method="stop"), 
        Bunch(name="hash_check", label="HASH", options=("-H", "--hash-check"), help="hash-check torrent", interactive=True), 
        Bunch(name="delete", options=("--delete",), help="remove torrent from client", interactive=True), 
        Bunch(name="throttle", options=("-T", "--throttle",), argshelp="NAME", method="set_throttle",
            help="assign to named throttle group (NULL=unlimited, NONE=global)", interactive=True), 
        Bunch(name="tag", options=("--tag",), argshelp='"TAG +TAG -TAG..."',
            help="add or remove tag(s)", interactive=False), 
        # TODO:
        # Bunch(name="xmlrpc", options=("--xmlrpc",), argshelp="CMD[,ARG1,...]", method="xmlrpc",
        #     help="call a raw XMLRPC command", interactive=True), 
    )
# TODO: implement --exterminate
#        self.add_bool_option("--exterminate", "--delete-all",
#            help="remove from client and also delete all data (implies -i)")
# TODO: --custom NAME=value
# TODO: implement --clean-partial
#        self.add_bool_option("--clean-partial",
#            help="remove partially downloaded 'off'ed files (also stops downloads)")
# TODO: --pause, --resume?


    def __init__(self):
        """ Initialize rtcontrol.
        """
        super(RtorrentControl, self).__init__()

        self.prompt = PromptDecorator(self)


    def add_options(self):
        """ Add program options.
        """
        super(RtorrentControl, self).add_options()

        # basic options
        self.add_bool_option("--help-fields",
            help="show available fields and their description")
        self.add_bool_option("-n", "--dry-run",
            help="don't commit changes, just tell what would happen")
        self.prompt.add_options()
      
        # output control
        self.add_bool_option("-0", "--nul", "--print0",
            help="use a NUL character instead of a linebreak after items")
        self.add_bool_option("--column-headers",
            help="print column headers")
        #self.add_bool_option("-f", "--full",
        #    help="print full torrent details")
        self.add_value_option("-o", "--output-format", "FORMAT",
            help="specify display format (use '-o-' to disable item display)")
        self.add_value_option("-s", "--sort-fields", "FIELD[,...]",
            help="fields used for sorting")
        self.add_bool_option("-r", "--reverse-sort",
            help="reverse the sort order")
# TODO: implement -S
#        self.add_bool_option("-S", "--summary",
#            help="print statistics")

        # torrent state change (actions)
        for action in self.ACTION_MODES:
            action.setdefault("label", action.name.upper())
            action.setdefault("method", action.name)
            action.setdefault("interactive", False)
            action.setdefault("argshelp", "")
            action.setdefault("args", ())
            if action.argshelp:
                self.add_value_option(*action.options + (action.argshelp,), **{"help": action.help + (" (implies -i)" if action.interactive else "")})
            else:
                self.add_bool_option(*action.options, **{"help": action.help + (" (implies -i)" if action.interactive else "")})
        self.add_value_option("--ignore", "|".join(self.IGNORE_OPTIONS),
            type="choice", choices=self.IGNORE_OPTIONS,
            help="set 'ignore commands' status on torrent")
# TODO: implement --move-data
#        self.add_value_option("--move-data", "DIR",
#            help="move data to given target directory (implies -i, can be combined with --delete)")
        self.add_bool_option("-F", "--flush", help="flush changes immediately (save session data)")


    def emit(self, item, defaults=None):
        """ Print an item to stdout.
        """
        output_format = self.options.output_format
        if item is None:
            # For headers, ensure we only have string formats
            output_format = re.sub(
                r"(\([_.a-zA-Z0-9]+\)[-#+0 ]?[0-9]*?)[.0-9]*[diouxXeEfFgG]", 
                lambda m: m.group(1) + 's', output_format) 

            # Use configured escape codes on a terminal
            if os.isatty(1):
                output_format = ''.join((config.output_header_ecma48, output_format, "\x1B[0m"))

        try:
            item_text = fmt.to_console(output_format % engine.OutputMapping(item, defaults)) 
        except (ValueError, TypeError), exc:
            self.fatal("Trouble with formatting item %r using %r" % (item, output_format), exc)
            raise

        if self.options.nul:
            sys.stdout.write(item_text + '\0')
            sys.stdout.flush()
        else: 
            print(item_text)

        return item_text.count('\n') + 1


    def validate_output_format(self, default_format):
        """ Prepare output format for later use.
        """
        output_format = self.options.output_format

        # Use default format if none is given
        if output_format is None:
            output_format = default_format

        # Check if it's a custom output format from configuration
        # (they take precedence over field names, so name them wisely)
        output_format = config.formats.get(output_format, output_format)

        # Expand plain field list to usable form
        if re.match(r"^[,._0-9a-zA-Z]+$", output_format):
            output_format = "%%(%s)s" % ")s\t%(".join(engine.validate_field_list(output_format, allow_fmt_specs=True))

        # Replace some escape sequences
        output_format = (output_format
            .replace(r"\\", "\\")
            .replace(r"\n", "\n")
            .replace(r"\t", "\t")
            .replace(r"\$", "\0") # the next 3 allow using $() instead of %()
            .replace("$(", "%(")
            .replace("\0", "$")
            .replace(r"\ ", " ") # to prevent stripping in config file
            #.replace(r"\", "\")
        )                            

        self.options.output_format = unicode(output_format)


    def validate_sort_fields(self):
        """ Take care of sorting.
        """
        sort_fields = self.options.sort_fields

        # Use default order if none is given
        if sort_fields is None:
            sort_fields = config.sort_fields

        # Split and validate field list
        sort_fields = engine.validate_field_list(sort_fields)

        self.options.sort_fields = sort_fields
        return operator.attrgetter(*tuple(self.options.sort_fields))


    def mainloop(self):
        """ The main loop.
        """
        # Print field definitions?
        if self.options.help_fields:
            self.parser.print_help()

            def custom_dynamic():
                "named rTorrent custom attribute, e.g. 'custom_completion_target'"
                return ("custom_KEY", custom_dynamic)

            print('')
            print("Fields are:")
            print("\n".join(["  %-21s %s" % (name, field.__doc__)
                for name, field in sorted(engine.FieldDefinition.FIELDS.items() + [custom_dynamic()])
            ]))
            sys.exit(1)

        # Print usage if no conditions are provided
        if not self.args:
            self.parser.error("No filter conditions given!")

        # Check special action options
        action = None
        if self.options.ignore:
            action = Bunch(name="ignore", method="ignore", label="IGNORE" if int(self.options.ignore) else "HEED", 
                help="commands on torrent", interactive=False, args=(self.options.ignore,))

        # Check standard action options
        for action_mode in self.ACTION_MODES:
            if getattr(self.options, action_mode.name):
                if action:
                    self.parser.error("Options --%s and --%s are mutually exclusive" % (
                        action.name.replace('_', '-'), action_mode.name.replace('_', '-'),
                    ))
                action = action_mode
                if action.argshelp:
                    action.args = (getattr(self.options, action.name),)
        if not action and self.options.flush:
            action = Bunch(name="flush", method="flush", label="FLUSH", 
                help="flush session data", interactive=False, args=())
            self.options.flush = False # No need to flush twice
        if action and action.interactive:
            self.options.interactive = True

#        print repr(config.engine)
#        config.engine.open()
#        print repr(config.engine)

        # Preparation steps
        self.validate_output_format(config.action_format if action else config.output_format)
        sort_key = self.validate_sort_fields()
        matcher = engine.parse_filter_conditions(self.args)

        # Find matching torrents
        items = list(config.engine.items())
        matches = [item for item in items if matcher.match(item)]
        matches.sort(key=sort_key, reverse=self.options.reverse_sort)

        if action:
            self.LOG.info("%s %s %d out of %d torrents." % (
                "Would" if self.options.dry_run else "About to", action.label, len(matches), len(items),
            ))

            # Perform chosen action on matches
            for item in matches:
                if not self.prompt.ask_bool("%s item %s" % (action.label, item.name)):
                    continue
                if self.options.output_format and self.options.output_format != "-":
                    self.emit(item, {"action": action.label}) 
                if not self.options.dry_run:
                    getattr(item, action.method)(*action.args)
                    if self.options.flush:
                        item.flush()
        else:
            # Display matches
            if self.options.output_format and self.options.output_format != "-":
                line_count = 0
                for item in matches:
                    # Emit a header line every 'output_header_frequency' lines
                    if self.options.column_headers and line_count % config.output_header_frequency == 0:
                        self.emit(None)

                    # Print matching item
                    line_count += self.emit(item)

            self.LOG.info("Filtered %d out of %d torrents." % (len(matches), len(items),))

        ##print; print repr(items[0])
        
        # print summary
#        if self.options.summary:
#            # TODO
#            pass


def run(): #pragma: no cover
    """ The entry point.
    """
    ScriptBase.setup()
    RtorrentControl().run()

