PREFIX ?= /usr/local
PYTHON ?= python3
BINDIR := $(DESTDIR)$(PREFIX)/bin
DATADIR := $(DESTDIR)$(PREFIX)/share/applications

.PHONY: install uninstall test check release

install:
	install -Dm755 hv-installer-gui.py $(BINDIR)/hv-installer-gtk
	install -Dm644 data/hvinstaller.desktop $(DATADIR)/hvinstaller.desktop

uninstall:
	rm -f $(BINDIR)/hv-installer-gtk
	rm -f $(DATADIR)/hvinstaller.desktop

check:
	$(PYTHON) -m py_compile hv-installer-gui.py
	$(PYTHON) -m unittest discover -s tests -v

test: check

release: check
	$(PYTHON) packaging/build-release.py
