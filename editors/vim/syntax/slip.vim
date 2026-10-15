if exists('b:current_syntax')
  finish
endif

syntax case match
syntax keyword slipType module logic bit int integer byte shortint longint time real
syntax keyword slipType signed unsigned input output inout wire reg typedef enum struct packed
syntax keyword slipType param localparam type bundle interface master slave bus string void
syntax keyword slipKeyword seq comb initial pos neg if else for case casez casex default
syntax keyword slipKeyword inside return assert static_assert include assign function automatic defun
syntax keyword slipConstant true false True False None
syntax match slipMeta /`\%(for\|if\|else\)\>/
syntax match slipMeta /`[A-Za-z_][A-Za-z0-9_]*/
syntax match slipSystem /\$[A-Za-z_][A-Za-z0-9_]*/
syntax match slipNumber /\<\d[0-9_]*\>/
syntax match slipNumber /\%(\<\d[0-9_]*\)\?'[sS]\?[bBoOdDhH][0-9a-fA-F_xXzZ?]\+/
syntax match slipNumber /'[01xXzZ]\>/
syntax match slipOperator /=>\|::\|<=\|>=\|==\|!=\|&&\|||/
syntax match slipPort /\.[A-Za-z_][A-Za-z0-9_]*/
syntax region slipString start=/"/ skip=/\\./ end=/"/
syntax keyword slipTodo TODO FIXME XXX NOTE contained
syntax region slipComment start=+//+ end=+$+ contains=slipTodo,@Spell
syntax region slipBlockComment start=+/\*+ end=+\*/+ contains=slipBlockComment,slipTodo,@Spell
syntax region slipAttribute start=/(\*/ end=/\*)/ contains=slipString,slipNumber
syntax sync fromstart

highlight default link slipType Type
highlight default link slipKeyword Keyword
highlight default link slipMeta PreProc
highlight default link slipSystem Function
highlight default link slipConstant Constant
highlight default link slipNumber Number
highlight default link slipOperator Operator
highlight default link slipPort Identifier
highlight default link slipString String
highlight default link slipComment Comment
highlight default link slipBlockComment Comment
highlight default link slipTodo Todo
highlight default link slipAttribute PreProc
let b:current_syntax = 'slip'
