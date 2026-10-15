local M = {}
local options = {}
local stopping = {}

local shared_settings = {
  'compiler', 'python', 'server_cmd', 'project', 'profile', 'indent_width',
  'check_on_save', 'open_quickfix', 'lsp_auto_start',
}

local function setting(name, default)
  return vim.fn['slip#setting'](name, default)
end

local function stop_client(client, force)
  stopping[client.id] = true
  if vim.fn.has('nvim-0.11') == 1 then
    client:stop(force)
  else
    client.stop(force)
  end
end

local function clients(buffer)
  if vim.lsp.get_clients then
    return vim.lsp.get_clients({ bufnr = buffer, name = 'slip' })
  end
  local result = {}
  for _, client in ipairs(vim.lsp.get_active_clients()) do
    if client.name == 'slip' and vim.lsp.buf_is_attached(buffer, client.id) then
      result[#result + 1] = client
    end
  end
  return result
end

local function matches(client, config)
  return client.name == 'slip' and not stopping[client.id] and not client:is_stopped()
    and client.config.root_dir == config.root_dir
    and vim.deep_equal(client.config.cmd, config.cmd)
    and vim.deep_equal(client.config.init_options, config.init_options)
end

local function start(quiet)
  if vim.bo.filetype ~= 'slip' or vim.api.nvim_buf_get_name(0) == '' then
    if not quiet then
      vim.notify('Open a named .slip buffer before starting the server.', vim.log.levels.WARN)
    end
    return
  end
  local context = vim.fn['slip#context']()
  local cmd = vim.fn['slip#server_command']()
  if #cmd == 0 or vim.fn.executable(context.compiler) == 0 then
    if not quiet then
      vim.notify('Slip LSP needs the compiler and slip-lsp (or the repository server with Python 3.10+). '
        .. 'Set g:slip_compiler and g:slip_server_cmd or g:slip_python.', vim.log.levels.WARN)
    end
    return
  end
  if context.profile ~= '' and context.project == '' then
    if not quiet then
      vim.notify('A Slip profile requires slip.conf; set g:slip_project.', vim.log.levels.WARN)
    end
    return
  end
  local init_options = {
    compilerPath = context.compiler, project = context.project, profile = context.profile,
  }
  local config = {
    name = 'slip',
    cmd = cmd,
    cmd_cwd = context.root,
    root_dir = context.root,
    init_options = init_options,
    capabilities = options.capabilities or vim.lsp.protocol.make_client_capabilities(),
    on_exit = function(_, _, id)
      stopping[id] = nil
    end,
    on_attach = function(client, buffer)
      vim.bo[buffer].omnifunc = 'v:lua.vim.lsp.omnifunc'
      vim.bo[buffer].tagfunc = 'v:lua.vim.lsp.tagfunc'
      if options.on_attach then
        options.on_attach(client, buffer)
      end
    end,
  }
  for _, client in ipairs(clients(0)) do
    if not matches(client, config) then
      vim.lsp.buf_detach_client(0, client.id)
      if next(client.attached_buffers) == nil then
        stop_client(client)
      end
    end
  end
  return vim.lsp.start(config, {
    -- Keep configurations with different profiles/compilers in separate clients.
    reuse_client = matches,
  })
end

function M.start()
  return start(false)
end

function M.autostart()
  local enabled = setting('lsp_auto_start', 1)
  if enabled ~= 0 and enabled ~= false then
    return start(true)
  end
end

function M.stop()
  -- Detach this buffer; keep a shared client alive for other project buffers.
  for _, client in ipairs(clients(0)) do
    vim.lsp.buf_detach_client(0, client.id)
    if next(client.attached_buffers) == nil then
      stop_client(client)
    end
  end
end

function M.restart()
  local buffers = { [vim.api.nvim_get_current_buf()] = true }
  for _, client in ipairs(clients(0)) do
    for buffer in pairs(client.attached_buffers) do
      buffers[buffer] = true
    end
    stop_client(client, true)
  end
  vim.defer_fn(function()
    for buffer in pairs(buffers) do
      if vim.api.nvim_buf_is_valid(buffer) and vim.api.nvim_buf_is_loaded(buffer)
          and vim.bo[buffer].filetype == 'slip' then
        vim.api.nvim_buf_call(buffer, function() start(false) end)
      end
    end
  end, 100)
end

function M.setup(config)
  options = vim.tbl_extend('force', options, config or {})
  for _, key in ipairs(shared_settings) do
    if options[key] ~= nil then
      vim.g['slip_' .. key] = options[key]
    end
  end
  for _, buffer in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_loaded(buffer) and vim.bo[buffer].filetype == 'slip' then
      vim.api.nvim_buf_call(buffer, M.autostart)
    end
  end
end

return M
