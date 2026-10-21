"use client";

import { createContext, useContext } from "react";

/** True once the intro has finished, so pages can start their entrance. */
export const ReadyContext = createContext(false);
export const useReady = () => useContext(ReadyContext);
