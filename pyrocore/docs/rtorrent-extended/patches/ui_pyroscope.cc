#include "ui_pyroscope.h"

#include "config.h"
#include "globals.h"

#include <iostream>

//#include <rak/functional.h>
//#include <rak/functional_fun.h>
//#include <sigc++/adaptors/bind.h>

#include "rpc/command_variable.h"
#include "core/view.h"
#include "core/download.h"
#include "torrent/rate.h"
#include "display/window.h"
#include "display/canvas.h"

#include "command_helpers.h"


typedef std::pair<core::View::iterator, core::View::iterator> Range;

static unsigned long attr_map[ps::COL_MAX] = {0};

static const char* color_names[] = {
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"
};

static const char* color_vars[ps::COL_MAX] = {
	0,
	"ui.color.complete",
	"ui.color.seeding",
	"ui.color.incomplete",
	"ui.color.leeching",
	"ui.color.alarm",
	"ui.color.title",
	"ui.color.focus",
};

namespace display {

void split(std::vector<std::string>& words, const char* str, char delim = ' ') {
	do {
		const char* begin = str;
		while (*str && *str != delim) str++;
		words.push_back(std::string(begin, str));
	} while (*str++);
}


void ui_pyroscope_colormap_init() {
	for (int k = 1; k < ps::COL_MAX; k++) {
		init_pair(k, -1, -1);
		std::string col_def = rpc::call_command_string(color_vars[k]);
		if (col_def.empty()) continue;

		std::vector<std::string> words;
		split(words, col_def.c_str());

		short col[2] = {-1, -1};
		short col_idx = 0;
		unsigned long attr = A_NORMAL;
		for (int i = 0; i < words.size(); i++) {
			if (words[i] == "bold") attr |= A_BOLD;
			else if (words[i] == "standout") attr |= A_STANDOUT;
			else if (words[i] == "underline") attr |= A_UNDERLINE;
			else if (words[i] == "reverse") attr |= A_REVERSE;
			else if (words[i] == "blink") attr |= A_BLINK;
			else if (words[i] == "dim") attr |= A_DIM;
			else if (words[i] == "on") col_idx = 1;
			else for (short c = 0; c < 8; c++) {
				if (words[i] == color_names[c]) {
					col[col_idx] = c;
					break;
				}
			}
		}
		attr_map[k] = attr;
		init_pair(k, col[0], col[1]);
	}
}


void ui_pyroscope_canvas_init() {
 	start_color();
	use_default_colors();
	ui_pyroscope_colormap_init();
}


void ui_pyroscope_download_list_redraw(display::Window* window, core::View* view, display::Canvas* canvas, int pos, Range& range) {
	pos -= 3;
	canvas->set_attr(0, 0, -1, attr_map[ps::COL_TITLE], ps::COL_TITLE);

	if (range.first == view->focus()) {
		for (int i = 0; i < 3; i++ ) {
			canvas->set_attr(0, pos+i, 1, attr_map[ps::COL_FOCUS], ps::COL_FOCUS);
		}
	}

	// download title color
	torrent::Download* item = (*range.first)->download();
	int title_col;
	if ((*range.first)->is_done())
		title_col = item->up_rate()->rate() ? ps::COL_SEEDING : ps::COL_COMPLETE;
	else
		title_col = item->down_rate()->rate() ? ps::COL_LEECHING : ps::COL_INCOMPLETE;
	canvas->set_attr(3, pos, -1, attr_map[title_col], title_col);

	// message alert
	if (!(*range.first)->message().empty()) {
		canvas->set_attr(1, pos, 1, attr_map[ps::COL_ALARM], ps::COL_ALARM);
		canvas->set_attr(1, pos+1, 1, attr_map[ps::COL_ALARM], ps::COL_ALARM);
		canvas->set_attr(1, pos+2, -1, attr_map[ps::COL_ALARM], ps::COL_ALARM);
	}
}

} // namespace


const torrent::Object rpc::CommandVariable::set_color_string(Command* rawCommand, cleaned_type target, const torrent::Object& rawArgs) {
	rpc::CommandVariable::set_string(rawCommand, target, rawArgs);
	display::ui_pyroscope_colormap_init();
}


void initialize_command_ui_pyroscope() {
#if defined(CMD2_ANY)
#else
	#define NEW_VARIABLE_STRING(key, defaultValue) \
		add_variable(key, key ".set", 0, \
			&rpc::CommandVariable::get_string, &rpc::CommandVariable::set_color_string, std::string(defaultValue));

	NEW_VARIABLE_STRING("ui.color.complete", 	"green");
	NEW_VARIABLE_STRING("ui.color.seeding", 	"bold green");
	NEW_VARIABLE_STRING("ui.color.incomplete", 	"cyan");
	NEW_VARIABLE_STRING("ui.color.leeching", 	"bold cyan");
	NEW_VARIABLE_STRING("ui.color.alarm", 		"bold yellow on red");
	NEW_VARIABLE_STRING("ui.color.title", 		"bold");
	NEW_VARIABLE_STRING("ui.color.focus", 		"standout");
#endif
}
