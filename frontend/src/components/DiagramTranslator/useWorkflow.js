import { useReducer, useCallback } from 'react';

export const DEFAULT_CHAT_MESSAGE = {
  role: 'assistant',
  content: 'Hi! I\'m your **IaC Assistant**. I can help you modify your Terraform/Bicep code. Try asking me to:\n\n- Add VNet with subnets and NSGs\n- Configure public/private IPs\n- Add storage accounts\n- Apply naming conventions\n- Set up monitoring & diagnostics\n- Add Key Vault access policies\n\nWhat would you like to change?',
};

const initialState = {
  step: 'upload',
  diagramId: null,
  jobId: null,
  analysis: null,
  questions: [],
  answers: {},
  iacCode: null,
  iacFormat: 'terraform',
  costEstimate: null,
  exportLoading: {},
  loading: false,
  error: null,
  analyzeProgress: [],
  // UX
  dragOver: false,
  selectedFile: null,
  filePreviewUrl: null,
  copyFeedback: {},
  confirmReset: false,
  // HLD
  hldData: null,
  hldLoading: false,
  hldTab: 'overview',
  hldExportLoading: {},
  hldIncludeDiagrams: true,
  // IaC Chat
  iacChatOpen: false,
  iacChatMessages: [DEFAULT_CHAT_MESSAGE],
  iacChatInput: '',
  iacChatLoading: false,
};

function reducer(state, action) {
  switch (action.type) {
    case 'SET':
      return { ...state, ...action.payload };
    case 'ADD_PROGRESS':
      return { ...state, analyzeProgress: [...state.analyzeProgress, action.payload] };
    case 'ADD_CHAT_MESSAGE':
      return { ...state, iacChatMessages: [...state.iacChatMessages, action.payload] };
    case 'SET_COPY_FEEDBACK':
      return { ...state, copyFeedback: { ...state.copyFeedback, [action.key]: action.value } };
    case 'SET_EXPORT_LOADING':
      return { ...state, exportLoading: { ...state.exportLoading, [action.key]: action.value } };
    case 'SET_HLD_EXPORT_LOADING':
      return { ...state, hldExportLoading: { ...state.hldExportLoading, [action.key]: action.value } };
    case 'UPDATE_ANSWER':
      return { ...state, answers: { ...state.answers, [action.key]: action.value } };
    case 'RESET':
      return { ...initialState };
    default:
      return state;
  }
}

export default function useWorkflow() {
  const [state, dispatch] = useReducer(reducer, initialState);

  const set = useCallback((payload) => dispatch({ type: 'SET', payload }), []);
  const addProgress = useCallback((msg) => dispatch({ type: 'ADD_PROGRESS', payload: msg }), []);
  const addChatMessage = useCallback((msg) => dispatch({ type: 'ADD_CHAT_MESSAGE', payload: msg }), []);
  const setExportLoading = useCallback((key, value) => dispatch({ type: 'SET_EXPORT_LOADING', key, value }), []);
  const setHldExportLoading = useCallback((key, value) => dispatch({ type: 'SET_HLD_EXPORT_LOADING', key, value }), []);
  const updateAnswer = useCallback((key, value) => dispatch({ type: 'UPDATE_ANSWER', key, value }), []);
  const reset = useCallback(() => dispatch({ type: 'RESET' }), []);

  const copyWithFeedback = useCallback((text, key) => {
    navigator.clipboard.writeText(text);
    dispatch({ type: 'SET_COPY_FEEDBACK', key, value: true });
    setTimeout(() => dispatch({ type: 'SET_COPY_FEEDBACK', key, value: false }), 2000);
  }, []);

  return {
    state,
    dispatch,
    set,
    addProgress,
    addChatMessage,
    setExportLoading,
    setHldExportLoading,
    updateAnswer,
    reset,
    copyWithFeedback,
  };
}
