use std::path::{Component, Path, PathBuf};

pub const API_CONFLICT: &str =
    "crow_configuration_alias_conflict:CROW_COLLECTOR_API_BASE,FAPAI_COLLECTOR_API_BASE";
pub const PYTHON_CONFLICT: &str =
    "crow_configuration_alias_conflict:CROW_DESKTOP_PYTHON_PATH,FAPAI_DESKTOP_PYTHON_PATH";

pub fn select(
    canonical: Option<String>,
    legacy: Option<String>,
    equivalent: impl Fn(&str, &str) -> bool,
    error: &'static str,
) -> Result<Option<String>, &'static str> {
    if let (Some(new), Some(old)) = (&canonical, &legacy) {
        if !equivalent(new, old) {
            return Err(error);
        }
    }
    Ok(canonical.or(legacy))
}

pub fn api_source(
    canonical: Option<String>,
    legacy: Option<String>,
    saved: impl FnOnce() -> Result<Option<String>, &'static str>,
) -> Result<Option<String>, &'static str> {
    match select(canonical, legacy, |a, b| a == b, API_CONFLICT)?
        .filter(|value| !value.trim().is_empty())
    {
        Some(value) => Ok(Some(value)),
        None => saved(),
    }
}

// Saved interpreter paths must be absolute. Compare spelling, never follow links.
pub fn same_absolute_path(left: &str, right: &str) -> bool {
    if left == right {
        return true;
    }
    fn normalized(value: &str) -> Option<PathBuf> {
        let path = Path::new(value);
        if !path.is_absolute() {
            return None;
        }
        let mut result = PathBuf::new();
        for part in path.components() {
            match part {
                Component::CurDir => {}
                Component::ParentDir => {
                    result.pop();
                }
                other => result.push(other.as_os_str()),
            }
        }
        Some(result)
    }
    match (normalized(left), normalized(right)) {
        (Some(left), Some(right)) => {
            #[cfg(windows)]
            {
                left.to_string_lossy().to_lowercase() == right.to_string_lossy().to_lowercase()
            }
            #[cfg(not(windows))]
            {
                left == right
            }
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aliases_are_scoped_and_conflicts_never_contain_values() {
        for (new, old) in [(Some("x"), None), (None, Some("x")), (Some("x"), Some("x"))] {
            assert_eq!(
                select(
                    new.map(str::to_owned),
                    old.map(str::to_owned),
                    |a, b| a == b,
                    API_CONFLICT
                ),
                Ok(Some("x".into()))
            );
        }
        assert_eq!(
            select(
                Some("private-one".into()),
                Some("private-two".into()),
                |a, b| a == b,
                API_CONFLICT
            ),
            Err(API_CONFLICT)
        );
        assert_eq!(
            select(
                Some("".into()),
                Some("x".into()),
                |a, b| a == b,
                API_CONFLICT
            ),
            Err(API_CONFLICT)
        );
        assert_eq!(select(None, None, |a, b| a == b, API_CONFLICT), Ok(None));
    }

    #[test]
    fn process_group_overrides_saved_group_and_empty_retains_old_fallback() {
        for (new, old) in [(Some("override"), None), (None, Some("override"))] {
            assert_eq!(
                api_source(new.map(str::to_owned), old.map(str::to_owned), || panic!(
                    "saved must not be read"
                )),
                Ok(Some("override".into()))
            );
        }
        assert_eq!(
            api_source(Some(" ".into()), None, || Ok(Some("saved".into()))),
            Ok(Some("saved".into()))
        );
        assert_eq!(
            api_source(None, None, || Err(API_CONFLICT)),
            Err(API_CONFLICT)
        );
        assert_eq!(
            api_source(Some("one".into()), Some("two".into()), || panic!(
                "conflict must not fall back"
            )),
            Err(API_CONFLICT)
        );
    }

    #[test]
    fn path_equivalence_is_native_and_lexical() {
        #[cfg(windows)]
        {
            assert!(same_absolute_path(
                r"C:\Crow\python.exe",
                "c:/Crow/./python.exe"
            ));
            assert!(same_absolute_path(
                r"\\nas\share\python.exe",
                "//NAS/share/python.exe"
            ));
            assert!(!same_absolute_path("C:", "C:/"));
        }
        #[cfg(not(windows))]
        {
            assert!(same_absolute_path("/crow/bin/../python", "/crow/python"));
            assert!(!same_absolute_path("/Crow/python", "/crow/python"));
            assert!(!same_absolute_path("/crow/python\\", "/crow/python"));
        }
        assert!(same_absolute_path("", ""));
        assert!(!same_absolute_path("relative/python", "relative/./python"));
    }
}
