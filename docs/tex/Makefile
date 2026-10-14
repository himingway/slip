TEX      := user-manual
PDF      := $(TEX).pdf
LATEX    := xelatex
FLAGS    := -interaction=nonstopmode -halt-on-error
EXAMPLES := ../../examples/features/design.slip \
            ../../examples/native-interface/design.slip \
            ../../examples/native-interface/ip/stream.sv \
            ../../examples/native-interface/slip.conf

.PHONY: all clean view

all: $(PDF)

$(PDF): $(TEX).tex $(EXAMPLES)
	$(LATEX) $(FLAGS) $(TEX)
	$(LATEX) $(FLAGS) $(TEX)
	$(LATEX) $(FLAGS) $(TEX)

clean:
	rm -f $(PDF) $(TEX).aux $(TEX).log $(TEX).out $(TEX).toc $(TEX).bbl $(TEX).blg $(TEX).fdb_latexmk $(TEX).fls $(TEX).xdv $(TEX).bcf $(TEX).run.xml

view: $(PDF)
	xdg-open $(PDF) 2>/dev/null || open $(PDF) 2>/dev/null &
